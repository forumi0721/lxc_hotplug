# AGENTS.md: LXC USB Hotplug Agent Specification (Python 3)

본 문서는 Proxmox VE 호스트에서 실행되는 **Host Agent**와 Privileged LXC 컨테이너 내부에서 실행되는 **Guest Agent**의 내부 아키텍처, 보안 모델, 상태 머신, 장치 필터링, 미지의 장치 대응 및 통신 규격을 정의합니다.

구현 언어는 **Pure Python 3 (외부 pip 패키지 의존성 0%, 표준 라이브러리 전용)**를 기준으로 합니다.
기술적 실현 가능성 및 커널 인터페이스 분석은 [TECH_ANALYSIS.md](file:///home/forumi0721/lxc_hotplug/TECH_ANALYSIS.md)를 참조하십시오.

---

## 1. 시스템 아키텍처 및 1차 구현 범위

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   HOST (Proxmox VE) - Python 3                         │
│                                                                                        │
│   ┌───────────────────┐        ┌───────────────────────┐    ┌──────────────────────┐   │
│   │ udev Monitor      │ ───>   │ Active Device Cache   │ ──>│ cgroup2 Manager      │   │
│   │ (Kernel Netlink)  │        │ (State & Enriched DB) │    │ (Tiered Unknown Fix) │   │
│   └───────────────────┘        └──────────┬────────────┘    └──────────────────────┘   │
│                                           │                                            │
│                                           ▼                                            │
│                                ┌──────────────────────┐                                │
│                                │ Host IPC Server      │                                │
│                                │ (VMID Isolated Sockets)                               │
│                                └──────────┬───────────┘                                │
└───────────────────────────────────────────┼────────────────────────────────────────────┘
                                            │ Unix Domain Socket: /run/lxc-hotplug/<vmid>.sock
┌───────────────────────────────────────────┼────────────────────────────────────────────┐
│                                           ▼                                            │
│                                ┌──────────────────────┐                                │
│                                │ Guest IPC Client     │                                │
│                                │ (Auto-Reconnect)     │                                │
│                                └──────────┬───────────┘                                │
│                                           │                                            │
│   ┌───────────────────┐        ┌──────────▼───────────┐    ┌───────────────────────┐   │
│   │ Target /dev       │ <───   │ Device Node Engine   │ <──│ Guest Filter Engine   │   │
│   │ (os.mknod/unlink) │        │ (Privileged mknod)   │    │ (VID/PID/Subsystem)   │   │
│   └───────────────────┘        └──────────────────────┘    └───────────▲───────────┘   │
│                                                                        │               │
│                                                            ┌───────────┴───────────┐   │
│                                                            │ Timer Engine          │   │
│                                                            │ (10s / +5s / 3s)      │   │
│                                                            └───────────┬───────────┘   │
│                                                                        │               │
│                                                            ┌───────────▼───────────┐   │
│                                                            │ Trigger & Hook Engine │   │
│                                                            │ (udevadm / script)    │   │
│                                                            └───────────────────────┘   │
│                        GUEST (LXC Container - Privileged) - Python 3                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 보안 아키텍처 및 미지의 장치(Unknown Major) 대응

### 2.1 다중 방어선 (Defense-in-Depth)
1. **소켓 격리**: `/run/lxc-hotplug/<vmid>.sock` 전용 소켓 (0600 권한)으로 타 컨테이너 스누핑 원천 차단
2. **호스트 cgroup v2 하드 배리어**: 허용되지 않은 블록 디바이스(호스트 스토리지)에 대한 접근 커널 차단
3. **게스트 정책 화이트리스트**: 호스트가 이벤트를 보내더라도 게스트의 `guest.yaml` 설정과 일치하지 않는 장치는 노드 생성을 거부(Drop)

### 2.2 미지의 장치(Unknown Major/Minor) 유입 시 3단계 대응 전략
기존에 등록되지 않은 생소한 Major 번호(예: 특수 장비, 신규 드라이버의 동적 Major)를 가진 장비가 유입될 때:
- **Tier 1 (기본 권장 설정)**:
  - 컨테이너 설정(`/etc/pve/lxc/<vmid>.conf`)에 `lxc.cgroup2.devices.allow: c *:* rwm` 지정.
  - Privileged 컨테이너 환경에서 모든 캐릭터 디바이스를 수용할 수 있게 열어두고, 실질적인 접근 통제는 Guest Agent의 화이트리스트 필터가 수행합니다.
- **Tier 2 (Host Agent 동적 권한 인젝션)**:
  - 컨테이너 설정에 해당 Major가 사전 허용되어 있지 않은 경우, Host Agent가 `subprocess.run(["lxc-device", "-n", str(vmid), "add", f"/dev/{devname}"])`를 런타임에 호출하여 cgroup v2 eBPF 프로그램에 허용 룰을 즉시 주입합니다.
- **Tier 3 (로깅 및 플래그 전송)**:
  - 주입 실패 시 로그를 남기고 Guest로 전송되는 이벤트에 `"cgroup_allowed": false` 플래그를 표기하여 게스트의 불필요한 재시도를 차단합니다.

---

## 3. Host Agent 내부 규격 (`host_agent.py`)

### 3.1 사용 표준 라이브러리
`socket`, `select`, `os`, `sys`, `json`, `time`, `subprocess`, `signal`, `logging`

### 3.2 핵심 모듈 및 동작 로직
1. **Netlink Uevent Listener**:
   - `socket(AF_NETLINK, SOCK_RAW, NETLINK_KOBJECT_UEVENT)`를 바인드하여 커널 uevent를 논블로킹으로 수신.
   - Null 바이트(`\0`)로 구분된 환경변수 버퍼를 파싱하여 `ACTION`, `SUBSYSTEM`, `DEVNAME`, `MAJOR`, `MINOR`, `DEVPATH` 추출.
2. **Active Device Cache & Metadata Resolver**:
   - `add` 이벤트 시: `/sys<DEVPATH>`의 상위 트리를 탐색하여 `idVendor`, `idProduct`, `manufacturer`, `product`, `serial` 속성을 읽어 캐시(`dict`)에 저장.
   - `remove` 이벤트 시: `devpath`로 캐시를 역추적하여 원래의 메타데이터를 포함한 Enriched Event 생성 후 캐시 삭제.
3. **IPC Unix Server Manager**:
   - 컨테이너별 소켓 경로(`/run/lxc-hotplug/<vmid>.sock`) 관리.
   - 게스트 접속 시 `INITIAL_SYNC` 메시지로 현재 활성 디바이스 캐시 스냅샷 전체 전송.

---

## 4. Guest Agent 내부 규격 (`guest_agent.py`)

### 4.1 사용 표준 라이브러리
`socket`, `select`, `os`, `stat`, `sys`, `json`, `time`, `fnmatch`, `subprocess`, `signal`, `logging`

### 4.2 핵심 모듈 및 동작 로직
1. **IPC Client & Auto-Reconnect**:
   - `/run/lxc-hotplug/<vmid>.sock` 소켓 파일 감시 및 접속.
   - 단절 시 지수 백오프(2s, 4s, 8s, 최대 30s)로 자동 재연결 및 스냅샷 동기화.
2. **Rule Matcher (Filter Engine)**:
   - `guest.yaml` 설정 파싱.
   - `subsystem`, `vendor_id`, `product_id`, `serial`, `devname_pattern` (fnmatch) 검사. 매칭되지 않으면 즉시 폐기.
3. **Device Node Operator**:
   - **생성**: `os.makedirs(dirname, exist_ok=True)`, `os.mknod(path, stat.S_IFCHR | 0o660, os.makedev(major, minor))`.
   - **삭제**: `if os.path.exists(path): os.unlink(path)`.
4. **Monotonic Debounce Timer Engine**:
   - `time.monotonic()` 기반 타이머 (10s 시작, 추가 시 +5s 연장, 3초 무변동 시 조기 종료).
5. **Post-Trigger Engine**:
   - 안정화 완료 시 `subprocess.run(["udevadm", "trigger"])` 호출 (예외 무시).
   - 설정 파일에 정의된 `hook_script` 실행 (환경변수로 변경 목록 전달).

---

## 5. IPC 통신 프로토콜 사양 (Unix Domain Socket)

JSON Lines (`\n` 구분) 형식을 사용합니다.

### 5.1 메시지 규격

#### 1) 초기 연결 핸드셰이크 (Guest -> Host)
```json
{
  "type": "HELLO",
  "vmid": 100,
  "version": "1.0.0",
  "timestamp": "2026-09-28T16:08:00Z"
}
```

#### 2) 전체 상태 동기화 (Host -> Guest)
```json
{
  "type": "INITIAL_SYNC",
  "seq": 42,
  "devices": [
    {
      "subsystem": "tty",
      "devname": "ttyUSB0",
      "devpath": "/devices/pci0000:00/.../ttyUSB0",
      "major": 188,
      "minor": 0,
      "vendor_id": "10c4",
      "product_id": "ea60",
      "vendor": "Silicon Labs",
      "product": "CP2102 USB to UART",
      "serial": "0001",
      "cgroup_allowed": true
    }
  ],
  "timestamp": "2026-09-28T16:08:01Z"
}
```

#### 3) 실시간 핫플러그 이벤트 (Host -> Guest)

##### Add 이벤트
```json
{
  "type": "HOTPLUG_EVENT",
  "seq": 43,
  "action": "add",
  "device": {
    "subsystem": "hidraw",
    "devname": "hidraw0",
    "devpath": "/devices/pci0000:00/.../hidraw0",
    "major": 243,
    "minor": 0,
    "vendor_id": "046d",
    "product_id": "c52b",
    "vendor": "Logitech, Inc.",
    "product": "Unifying Receiver",
    "serial": null,
    "cgroup_allowed": true
  },
  "timestamp": "2026-09-28T16:08:10Z"
}
```

##### Remove 이벤트 (Host 캐시에서 역추적된 Enriched 메타데이터)
```json
{
  "type": "HOTPLUG_EVENT",
  "seq": 44,
  "action": "remove",
  "device": {
    "subsystem": "hidraw",
    "devname": "hidraw0",
    "devpath": "/devices/pci0000:00/.../hidraw0",
    "major": 243,
    "minor": 0,
    "vendor_id": "046d",
    "product_id": "c52b",
    "vendor": "Logitech, Inc.",
    "product": "Unifying Receiver",
    "serial": null,
    "cgroup_allowed": true
  },
  "timestamp": "2026-09-28T16:08:25Z"
}
```

---

## 6. 설정 파일 규격

### 6.1 Host 설정 (`/etc/lxc-hotplug/host.yaml`)
```yaml
socket_dir: "/run/lxc-hotplug"
shared_dev_base: "/dev/.lxc/dev"

# 기본 모니터링 서브시스템
subsystems:
  - hidraw
  - hiddev
  - tty
  - sound

# VMID별 매핑 및 cgroup 자동 관리 활성화
containers:
  - vmid: 100
    enabled: true
    # 미지의 Major 유입 시 lxc-device add 동적 호출 여부
    dynamic_cgroup_inject: true
```

### 6.2 Guest 설정 (`/etc/lxc-hotplug/guest.yaml`)
```yaml
vmid: 100
socket_path: "/run/lxc-hotplug/100.sock"
target_dev_dir: "/dev"

# 타이머 파라미터
timer:
  initial_window_sec: 10
  extend_window_sec: 5
  max_window_sec: 30
  inactivity_sec: 3

# 트리거 후처리
trigger:
  udevadm_trigger: true
  hook_script: "/etc/lxc-hotplug/hooks.d/on-change.sh"

# 게스트 수용 룰셋 (하나라도 매칭되면 수용, 비어있으면 전체 거부)
filters:
  # 모든 ttyACM 및 ttyUSB 수용
  - subsystem: "tty"
    devname_pattern: "ttyACM*|ttyUSB*"

  # 특정 VID/PID USB 오디오 카드 수용
  - subsystem: "sound"
    vendor_id: "0d8c"
    product_id: "0014"

  # 특정 로지텍 리시버 수용
  - subsystem: "hidraw"
    vendor_id: "046d"
    product_id: "c52b"
```
