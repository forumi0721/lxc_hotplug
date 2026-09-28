# AGENTS.md: LXC USB Hotplug Agent Specification (Python 3)

본 문서는 Proxmox VE 호스트에서 실행되는 **Host Agent**와 Privileged LXC 컨테이너 내부에서 실행되는 **Guest Agent**의 내부 아키텍처, 보안 모델, 상태 머신, 장치 필터링, 미지의 장치 대응 및 통신 규격을 정의합니다.

구현 언어는 **Pure Python 3 (외부 pip 패키지 의존성 0%, 표준 라이브러리 전용)**를 기준으로 합니다.

---

## 1. 시스템 아키텍처 및 1차 구현 범위

호스트의 실제 `/dev` 디렉토리는 컨테이너의 `/dev/.lxc/dev` 경로로 바인드 마운트(`ro=1`)되어 실시간 미러 뷰 역할을 합니다.  
Guest Agent는 소켓 이벤트를 받으면 `/dev/.lxc/dev/<devname>`를 참조(`os.stat`)하여 컨테이너 내부의 `/dev/<devname>`로 동일한 캐릭터 디바이스 노드를 `os.mknod`로 복제 생성합니다.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   HOST (Proxmox VE) - Python 3                         │
│                                                                                        │
│   ┌───────────────────┐        ┌───────────────────────┐    ┌──────────────────────┐   │
│   │ udev Monitor      │ ───>   │ Active Device Cache   │ ──>│ cgroup2 Manager      │   │
│   │ (Kernel Netlink)  │        │ (State & Enriched DB) │    │ (Tiered Unknown Fix) │   │
│   └───────────────────┘        └──────────┬────────────┘    └──────────────────────┘   │
│             │                             │                                            │
│             ▼                             ▼                                            │
│   [호스트 실제 /dev]            ┌──────────────────────┐                                │
│   (커널 udev가 노드 자동생성)   │ Host IPC Server      │                                │
│             │                   │ (VMID Isolated Sock) │                                │
│             │                   └──────────┬───────────┘                                │
└─────────────┼──────────────────────────────┼────────────────────────────────────────────┘
              │                              │
              │ PVE Bind Mount (mp0)         │ Unix Domain Socket: /run/lxc-hotplug/<vmid>.sock
              ▼                              ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│   [/dev/.lxc/dev (호스트 /dev 뷰)] ┌──────────────────────┐                            │
│             │                      │ Guest IPC Client     │                            │
│             │                      │ (Auto-Reconnect)     │                            │
│             │                      └──────────┬───────────┘                            │
│             │                                 │                                        │
│             ▼                                 ▼                                        │
│   ┌───────────────────┐            ┌──────────────────────┐    ┌───────────────────┐   │
│   │ Target /dev       │ <───────── │ Device Node Engine   │ <──│ Guest Filter      │   │
│   │ (mknod / unlink)  │ (복제 생성)│ (Replicate from host)│    │ (VID/PID/Subsys)  │   │
│   └───────────────────┘            └──────────────────────┘    └───────────▲───────┘   │
│                                                                            │           │
│                                                                ┌───────────┴───────┐   │
│                                                                │ Timer Engine      │   │
│                                                                │ (10s / +5s / 3s)  │   │
│                                                                └───────────┬───────┘   │
│                                                                            │           │
│                                                                ┌───────────▼───────┐   │
│                                                                │ Trigger & Hook    │   │
│                                                                │ (udevadm / script)│   │
│                                                                └───────────────────┘   │
│                        GUEST (LXC Container - Privileged) - Python 3                   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 보안 아키텍처 및 미지의 장치(Unknown Major) 대응

### 2.1 다중 방어선 (Defense-in-Depth)
1. **소켓 격리**: `/run/lxc-hotplug/<vmid>.sock` 전용 소켓 (0600/0660 권한)으로 타 컨테이너 스누핑 원천 차단
2. **호스트 cgroup v2 하드 배리어**: 허용되지 않은 블록 디바이스(호스트 스토리지)에 대한 접근 커널 차단
3. **게스트 정책 화이트리스트**: 호스트의 `/dev` 전체가 마운트되어 있더라도, 컨테이너 `/dev`에는 `guest.yaml` 화이트리스트를 통과한 장치만 노드로 생성

### 2.2 미지의 장치(Unknown Major/Minor) 유입 시 3단계 대응 전략
- **Tier 1 (기본 권장 설정)**:
  컨테이너 설정(`/etc/pve/lxc/<vmid>.conf`)에 `lxc.cgroup2.devices.allow: c *:* rwm` 지정.
- **Tier 2 (Host Agent 동적 권한 인젝션)**:
  컨테이너 설정에 해당 Major가 사전 허용되어 있지 않은 경우, Host Agent가 `subprocess.run(["lxc-device", "-n", str(vmid), "add", f"/dev/{devname}"])`를 런타임에 호출하여 cgroup v2 eBPF 프로그램에 허용 룰 주입.
- **Tier 3 (로깅 및 플래그 전송)**:
  주입 실패 시 로그를 남기고 Guest로 전송되는 이벤트에 `"cgroup_allowed": false` 플래그를 표기.

---

## 3. Host Agent 내부 규격 (`host_agent.py`)

### 3.1 핵심 모듈 및 동작 로직
1. **Netlink Uevent Listener**:
   - `socket(AF_NETLINK, SOCK_RAW, NETLINK_KOBJECT_UEVENT)`를 바인드하여 커널 uevent를 실시간 수신.
2. **Active Device Cache & Metadata Resolver**:
   - `add` 이벤트 시: `/sys<DEVPATH>`의 상위 트리를 탐색하여 `idVendor`, `idProduct`, `serial` 속성을 읽어 캐시에 저장.
   - `remove` 이벤트 시: `devpath`로 캐시를 역추적하여 원래의 메타데이터를 포함한 Enriched Event 생성 후 캐시 삭제.
3. **IPC Unix Server Manager**:
   - 컨테이너별 소켓 경로(`/run/lxc-hotplug/<vmid>.sock`) 관리.
   - 게스트 접속 시 `INITIAL_SYNC` 메시지로 현재 활성 디바이스 캐시 스냅샷 전체 전송.

---

## 4. Guest Agent 내부 규격 (`guest_agent.py`)

### 4.1 핵심 모듈 및 동작 로직
1. **IPC Client & Auto-Reconnect**:
   - `/run/lxc-hotplug/<vmid>.sock` 소켓 연결 및 단절 시 자동 재연결.
2. **Rule Matcher (Filter Engine)**:
   - `guest.yaml`의 화이트리스트 검사 (`subsystem`, `vendor_id`, `product_id`, `devname_pattern`).
3. **Device Node Operator**:
   - **생성**: 마운트된 호스트 `/dev` 경로(`/dev/.lxc/dev/<devname>`)를 `os.stat`하여 major/minor 번호를 확인한 후 컨테이너 내부의 `/dev/<devname>`에 `os.mknod(path, stat.S_IFCHR | 0o660, os.makedev(major, minor))` 생성.
   - **삭제**: `if os.path.exists(path): os.unlink(path)`.
4. **Monotonic Debounce Timer Engine**:
   - 10s 시작, 추가 시 +5s 연장(최대 30s), 3초 무변동 시 조기 종료.
5. **Post-Trigger Engine**:
   - 안정화 완료 시 `udevadm trigger` 및 `hook_script` 실행.

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
  "timestamp": "2026-09-28T23:28:00Z"
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
  "timestamp": "2026-09-28T23:28:01Z"
}
```

#### 3) 실시간 핫플러그 이벤트 (Host -> Guest)
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
  "timestamp": "2026-09-28T23:28:10Z"
}
```
