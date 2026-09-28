# LXC USB Hotplug

Proxmox VE 호스트와 LXC 컨테이너 간의 실시간 USB 디바이스 핫플러그(Hotplug) 자동 동기화 데몬 프로젝트입니다.

> **💡 핵심 구현 스택 & 타깃 환경**:
> - **구현 언어**: **Pure Python 3** (외부 의존성 및 pip 설치 0%, 표준 라이브러리 전용)
> - **1차 타깃 환경**: 디바이스 노드 직접 생성(`mknod`)이 가능한 **Privileged LXC Container**

---

## 📌 개요 및 동작 원리

LXC 컨테이너 내부에서 호스트의 전체 `/dev`를 기본 `/dev`로 통째로 대체하면 컨테이너 고유의 가상 터미널(pts), 공유 메모리(shm) 등의 격리가 깨집니다.  
따라서 **호스트의 `/dev`를 컨테이너의 `/dev/.lxc/dev`로 바인드 마운트(Mirror View)**하여 컨테이너가 호스트의 장치 상태를 볼 수 있게 하고, **Guest Agent가 필요한 장치만 컨테이너의 실제 `/dev`에 `mknod`로 선별 복제**하는 방식을 사용합니다.

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│ Host (Proxmox VE)                                                                 │
│                                                                                   │
│  [Kernel uevent] (USB Add / Remove)                                               │
│        │                                                                          │
│        ├──> [호스트 /dev] 에 커널 udev가 /dev/ttyUSB0 등 디바이스 노드 자동 생성    │
│        │          │                                                               │
│        ▼          │ (PVE Bind Mount: mp0: /dev,mp=/dev/.lxc/dev,ro=1)              │
│  [Host Agent]     │                                                               │
│        ├── 1. Active Device Cache 갱신 (Remove 시 역추적 및 스냅샷 유지)          │
│        ├── 2. cgroup2 devices.allow 권한 확인 및 lxc-device 지원                  │
│        └── 3. 컨테이너 전용 소켓으로 알림 전송 (/run/lxc-hotplug/<vmid>.sock)     │
└───────────────────┼─────────────────────────────────┬─────────────────────────────┘
                    │                                 │
                    │ Host /dev Mirror                │ Unix Domain Socket (JSON)
                    ▼                                 ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│ LXC Container (Guest - Privileged)                                                │
│                                                                                   │
│  [마운트된 호스트 /dev 뷰] ───> [/dev/.lxc/dev/ttyUSB0 ...] (호스트 장치 실시간 투영) │
│                                         │                                         │
│  [Guest Agent]                          │                                         │
│        ├── 1. 소켓 이벤트 수신 및 guest.yaml 화이트리스트 필터링 (VID/PID 매칭)    │
│        ├── 2. [/dev/.lxc/dev/<devname>] 에서 실제 장치 stat 확인 (major:minor)     │
│        ├── 3. 컨테이너 내부 [/dev/<devname>] 에 동일하게 mknod 생성!              │
│        ├── 4. 디바운스 타이머 가동 (10s 시작 / +5s 연장 / 3s 무변동 시 안정화)      │
│        └── 5. udevadm trigger 및 훅 스크립트 실행 ──> 서비스(HA, Z2M 등) 즉시 인식│
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔬 핵심 기술 아키텍처

### 1. 호스트 `/dev` 투영 (`/dev/.lxc/dev`)과 게스트 `mknod`
- **호스트는 노드 복제 불필요**: 리눅스 커널이 이미 호스트의 `/dev`에 장치 노드를 생성하므로, 호스트는 별도의 공유 노드를 생성할 필요가 없습니다.
- **게스트의 독립적 노드 생성**: 게스트는 `/dev/.lxc/dev/<devname>`을 `os.stat`하여 장치 타입과 `major:minor`를 읽어온 뒤, 컨테이너 내부의 표준 `/dev/<devname>`에 `os.mknod`로 생성합니다.
- **어플리케이션 호환성**: Home Assistant, Zigbee2MQTT, ALSA 등 컨테이너 내부 프로세스는 표준 경로(`/dev/ttyUSB0`, `/dev/snd/*` 등)를 그대로 사용할 수 있습니다.

### 2. 미지의 장치(Unknown Major/Minor) 유입 시 3단계 대응 전략
- **Tier 1 (기본 권장 설정)**:  
  Privileged 컨테이너 설정에 캐릭터 디바이스 전역 허용(`lxc.cgroup2.devices.allow: c *:* rwm`)을 등록합니다. 블록 디바이스(스토리지)는 보호되면서 모든 USB 캐릭터 디바이스가 커널 레벨에서 허용되며, 실제 노드 생성 통제는 게스트의 화이트리스트(`guest.yaml`)가 담당합니다.
- **Tier 2 (호스트 동적 권한 주입)**:  
  Tier 1을 열지 않은 컨테이너의 경우, Host Agent가 `lxc-device -n <vmid> add /dev/<devname>`를 백그라운드 호출하여 cgroup v2 eBPF 프로그램에 런타임 주입합니다.
- **Tier 3 (로깅 및 안전 플래그)**:  
  주입 실패 시 로그 기록 및 이벤트 페이로드에 `"cgroup_allowed": false` 플래그를 첨부합니다.

---

## 📋 Proxmox VE 설정 가이드

### 1. 호스트 디렉터리 준비
```bash
# 호스트(Proxmox)에서 통신 소켓 디렉터리 생성 및 권한 설정
mkdir -p /run/lxc-hotplug
chmod 755 /run/lxc-hotplug
```

### 2. LXC 컨테이너 설정 파일 (`/etc/pve/lxc/100.conf`)
```conf
# 1차 대상: Privileged 컨테이너 설정
unprivileged: 0

# 호스트의 실제 /dev 를 컨테이너의 /dev/.lxc/dev 로 바인드 마운트 (읽기 전용 추천)
mp0: /dev,mp=/dev/.lxc/dev,ro=1

# Hotplug 통신 소켓 디렉터리 마운트
mp1: /run/lxc-hotplug,mp=/run/lxc-hotplug,shared=1

# cgroup v2 캐릭터 디바이스 허용 (미지의 USB 장치 유연한 수용 권장)
lxc.cgroup2.devices.allow: c *:* rwm
```

---

## ⚙️ 설정 파일 규격

### Host 설정 (`/etc/lxc-hotplug/host.yaml`)
```yaml
socket_dir: "/run/lxc-hotplug"

# 모니터링 서브시스템
subsystems:
  - hidraw
  - hiddev
  - tty
  - sound

# 미지의 장치 유입 시 lxc-device add 동적 주입 시도
dynamic_cgroup_inject: true

# 대상 컨테이너 목록
containers:
  - vmid: 100
    enabled: true
```

### Guest 설정 (`/etc/lxc-hotplug/guest.yaml`)
```yaml
vmid: 100
socket_path: "/run/lxc-hotplug/100.sock"

# 호스트의 /dev 가 마운트된 컨테이너 내부 경로
host_dev_dir: "/dev/.lxc/dev"

# 컨테이너의 실제 타깃 /dev 경로
target_dev_dir: "/dev"

# 타이머 엔진 설정
timer:
  initial_window_sec: 10.0
  extend_window_sec: 5.0
  max_window_sec: 30.0
  inactivity_sec: 3.0

# 완료 시 후처리 액션
trigger:
  udevadm_trigger: true
  hook_script: "/etc/lxc-hotplug/hooks.d/on-change.sh"

# 게스트 디바이스 수용 필터 (화이트리스트: 일치하는 것만 /dev 에 mknod 생성)
filters:
  # 모든 Zigbee/시리얼 동글 허용
  - subsystem: "tty"
    devname_pattern: "ttyACM*|ttyUSB*"

  # 특정 USB 사운드카드만 허용 (VID:PID 지정)
  - subsystem: "sound"
    vendor_id: "0d8c"
    product_id: "0014"

  # 특정 HID 리시버만 허용
  - subsystem: "hidraw"
    vendor_id: "10c4"
```

---

## 📄 라이선스
MIT License
