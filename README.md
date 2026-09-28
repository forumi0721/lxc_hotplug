# LXC USB Hotplug

Proxmox VE 호스트와 LXC 컨테이너 간의 실시간 USB 디바이스 핫플러그(Hotplug) 자동 동기화 데몬 프로젝트입니다.

> **💡 핵심 구현 스택 & 타깃 환경**:
> - **구현 언어**: **Pure Python 3** (외부 의존성 및 pip 설치 0%, 표준 라이브러리 전용)
> - **1차 타깃 환경**: 디바이스 노드 직접 생성(`mknod`)이 가능한 **Privileged LXC Container**

---

## 📌 개요

LXC 컨테이너 환경에서는 호스트에 USB 디바이스가 연결(Add)되거나 분리(Remove)될 때 컨테이너 내부 `/dev` 노드와 cgroup 디바이스 접근 권한이 자동으로 갱신되지 않습니다.
이 프로젝트는 **Host Agent**와 **Guest Agent** 간의 격리된 Unix Domain Socket 통신을 통해, 호스트의 udev 이벤트를 실시간으로 전달하고 게스트 내부에서 조건에 맞는 장치만을 안전하게 동기화합니다.

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│ Host (Proxmox VE) - Python 3                                                      │
│                                                                                   │
│  [Kernel uevent] (AF_NETLINK Raw Socket)                                          │
│        │                                                                          │
│        ▼                                                                          │
│  [Host Agent (lxc-hotplug-host)]                                                  │
│        ├── 1. 장치 메타데이터 수집 (sysfs 역추적: VID/PID, Serial, devname)         │
│        ├── 2. Active Device Cache 갱신 (Remove 시 역추적 및 누적 상태 유지)          │
│        ├── 3. cgroup2 대응 (기존 장치 및 미지의 장치 동적 처리)                      │
│        ├── 4. 공유 디렉터리 미러링 (/dev/.lxc/dev/<vmid>/)                         │
│        └── 5. VMID별 전용 소켓으로 브로드캐스트/전송 (/run/lxc-hotplug/<vmid>.sock)  │
└─────────────────────────────────────────────┬─────────────────────────────────────┘
                                              │ Unix Domain Socket (JSON Lines)
┌─────────────────────────────────────────────▼─────────────────────────────────────┐
│ LXC Container (Guest - Privileged) - Python 3                                     │
│                                                                                   │
│  [Guest Agent (lxc-hotplug-guest)]                                                 │
│        ├── 1. 이벤트 수신 및 Guest 필터링 엔진 평가 (VID/PID, Subsystem 매칭)       │
│        ├── 2. 필터 통과 시 모니터링 타이머 활성화 (10s 시작 / 추가 시 +5s 연장)     │
│        ├── 3. 컨테이너 내부 /dev 에 직접 mknod 생성 및 unlink 삭제                   │
│        ├── 4. 3초간 추가 변동 없을 시 (Inactivity Debounce) 모니터링 종료           │
│        └── 5. udevadm trigger 실행 및 사용자 정의 Hook 스크립트 실행                 │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔬 핵심 기술 검토 결과

상세 기술 분석 내용은 [TECH_ANALYSIS.md](file:///home/forumi0721/lxc_hotplug/TECH_ANALYSIS.md)를 참고하십시오.

### 1. Pure Python 3 표준 라이브러리 100% 구현 검증
- **호스트 커널 Netlink**: `socket(AF_NETLINK, SOCK_RAW, NETLINK_KOBJECT_UEVENT)`를 통해 C 라이브러리(`libudev`) 없이 순수 파이썬으로 uevent 수신.
- **게스트 디바이스 노드 제어**: `os.mknod(path, stat.S_IFCHR | 0660, os.makedev(major, minor))` 및 `os.unlink()` 직접 호출.
- **디바운스 타이머 엔진**: `time.monotonic()` 기반의 논블로킹 이벤트 루프로 100ms 정밀도 보장.

### 2. 미지의 장치(Unknown Major/Minor) 유입 시 3단계 대응 전략
사전에 정의되지 않은 생소한 Major 번호(동적 할당 장비 등)가 꽂혔을 때의 처리 전략:
- **Tier 1 (기본 권장 - 최선의 운영 밸런스)**:  
  1차 대상이 Privileged 컨테이너이므로 PVE 설정에 캐릭터 디바이스 전역 허용(`lxc.cgroup2.devices.allow: c *:* rwm`)을 등록합니다. 블록 디바이스(스토리지)는 보호되면서 모든 USB 캐릭터 디바이스를 허용하며, 실제 생성 통제는 게스트의 화이트리스트가 담당합니다.
- **Tier 2 (동적 권한 인젝션)**:  
  Tier 1을 적용하지 않은 컨테이너의 경우, Host Agent가 `lxc-device -n <vmid> add /dev/<devname>`를 백그라운드 호출하여 cgroup v2 eBPF 프로그램에 해당 장치를 런타임에 즉시 추가합니다.
- **Tier 3 (관리자 로깅)**:  
  동적 주입 실패 시 로그 기록 및 이벤트 페이로드에 `"cgroup_allowed": false` 플래그를 첨부합니다.

---

## 🛡 다중 방어선 보안 체계 (Defense-in-Depth)

1. **소켓 격리**: VMID별 전용 소켓(`/run/lxc-hotplug/<vmid>.sock`, 권한 `0600`/`0660`)으로 타 컨테이너 간섭 차단
2. **호스트 cgroup 통제**: 블록 디바이스 원천 차단 및 인가된 캐릭터 디바이스 제어
3. **게스트 정책 필터링**: 호스트가 이벤트를 보내도 게스트 설정(`guest.yaml`)의 화이트리스트를 통과한 장치만 노드 생성

---

## 📋 Proxmox VE 설정 가이드

### 1. 호스트 디렉터리 준비
```bash
# 호스트(Proxmox)에서 디렉터리 생성 및 권한 설정
mkdir -p /dev/.lxc/dev/100
mkdir -p /run/lxc-hotplug
chmod 755 /dev/.lxc/dev
chmod 755 /run/lxc-hotplug
```

### 2. LXC 컨테이너 설정 파일 (`/etc/pve/lxc/100.conf`)
```conf
# 1차 대상: Privileged 컨테이너 설정
unprivileged: 0

# 디바이스 공유 볼륨 마운트
mp0: /dev/.lxc/dev/100,mp=/dev/.lxc/dev,shared=1

# Hotplug 통신 소켓 마운트
mp1: /run/lxc-hotplug,mp=/run/lxc-hotplug,shared=1

# cgroup v2 캐릭터 디바이스 허용 (미지의 USB 장치 유연한 수용 권장)
lxc.cgroup2.devices.allow: c *:* rwm

# 또는 특정 메이저 번호만 허용하고자 할 경우:
# 188: ttyUSB*, 166: ttyACM*, 116: sound, 243: hidraw
# lxc.cgroup2.devices.allow: c 188:* rwm
# lxc.cgroup2.devices.allow: c 166:* rwm
# lxc.cgroup2.devices.allow: c 116:* rwm
# lxc.cgroup2.devices.allow: c 243:* rwm
```

---

## ⚙️ Guest 필터링 설정 예시 (`guest.yaml`)

```yaml
vmid: 100
socket_path: "/run/lxc-hotplug/100.sock"
target_dev_dir: "/dev"
shared_dev_dir: "/dev/.lxc/dev"

# 타이머 엔진 설정
timer:
  initial_window_sec: 10
  extend_window_sec: 5
  max_window_sec: 30
  inactivity_sec: 3

# 완료 시 후처리 액션
trigger:
  udevadm_trigger: true
  hook_script: "/etc/lxc-hotplug/hooks.d/on-change.sh"

# 게스트 디바이스 수용 필터 (화이트리스트: 일치하는 것만 /dev 에 생성)
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
