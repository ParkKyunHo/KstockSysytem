"""
PRD v3.2 청산 로직 시나리오 차트 생성 스크립트
"""
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# 저장 경로
SAVE_PATH = Path(__file__).parent


def create_scenario_a():
    """시나리오 A: 정상 수익 실현 (분할익절 → EMA20 이탈)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    # 시간축 (09:30 ~ 14:00)
    times = np.linspace(0, 100, 200)

    # 가격 데이터 생성
    price = 10000 + np.concatenate([
        np.linspace(0, 300, 30),      # 상승
        np.linspace(300, 1500, 50),   # 급상승
        np.linspace(1500, 1200, 30),  # 조정
        np.linspace(1200, 800, 90)    # 하락 (EMA 이탈)
    ])

    # EMA20 (가격보다 부드럽게)
    ema20 = 10000 + np.concatenate([
        np.linspace(0, 150, 30),
        np.linspace(150, 900, 50),
        np.linspace(900, 1000, 30),
        np.linspace(1000, 900, 90)
    ])

    # 기준선들
    entry_price = 10000
    floor_line = 9850
    safety_net = entry_price * 0.965  # -3.5%

    # 차트 그리기
    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.plot(times, ema20, 'orange', linestyle='--', linewidth=1.5, label='EMA20')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가 (10,000원)')
    ax.axhline(y=floor_line, color='red', linestyle=':', alpha=0.7, label='Floor Line (9,850원)')
    ax.axhline(y=safety_net, color='darkred', linestyle='-', alpha=0.5, label='Safety Net (-3.5%)')

    # 주요 포인트 마커
    ax.plot(0, 10000, 'go', markersize=12, label='매수', zorder=5)
    ax.plot(30, 10300, 'yo', markersize=12, label='분할익절 (+3%)', zorder=5)
    ax.plot(180, 10800, 'ro', markersize=12, label='청산 (EMA20 이탈)', zorder=5)

    # 최고가 표시
    ax.plot(80, 11500, 'b^', markersize=10, zorder=5)
    ax.annotate('최고가\n11,500원', xy=(80, 11500), xytext=(90, 11700),
                fontsize=9, ha='center')

    # 포인트 주석
    ax.annotate('매수\n10,000원', xy=(0, 10000), xytext=(-10, 9700),
                fontsize=9, ha='center', color='green')
    ax.annotate('분할익절\n+3% (50주 매도)', xy=(30, 10300), xytext=(40, 10600),
                fontsize=9, ha='center', color='olive')
    ax.annotate('EMA20 이탈!\n청산 (종가 기준)', xy=(180, 10800), xytext=(165, 10500),
                fontsize=9, ha='center', color='red')

    ax.set_xlim(-5, 205)
    ax.set_ylim(9500, 12000)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 A: 정상 수익 실현 (분할익절 → 3분봉 EMA20 이탈)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    # 결과 텍스트
    result_text = "결과: 분할익절 +3% (50주) + EMA20청산 +8% (50주) = 평균 +5.5%"
    ax.text(100, 9600, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_a_normal_profit.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_a_normal_profit.png 생성 완료")


def create_scenario_b():
    """시나리오 B: 급등 후 급락 (Safety Lock 발동)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    times = np.linspace(0, 100, 150)

    # 가격: 급등 후 급락
    price = 10000 + np.concatenate([
        np.linspace(0, 300, 20),      # 상승 (+3%)
        np.linspace(300, 3000, 40),   # 급등 (+30%)
        np.linspace(3000, 2350, 30),  # 급락 (Safety Lock)
        np.linspace(2350, 2000, 60)   # 더 하락 (이미 청산됨)
    ])

    # EMA20
    ema20 = 10000 + np.concatenate([
        np.linspace(0, 200, 20),
        np.linspace(200, 1000, 40),
        np.linspace(1000, 1100, 30),
        np.linspace(1100, 1050, 60)
    ])

    entry_price = 10000

    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.plot(times, ema20, 'orange', linestyle='--', linewidth=1.5, label='EMA20')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가')

    # 이격도 110% 라인 (EMA20 * 1.10)
    disparity_line = ema20 * 1.10
    ax.plot(times, disparity_line, 'purple', linestyle=':', alpha=0.7, label='이격도 110%')

    # 마커
    ax.plot(0, 10000, 'go', markersize=12, zorder=5)
    ax.plot(20, 10300, 'yo', markersize=12, zorder=5)
    ax.plot(60, 13000, 'b^', markersize=10, zorder=5)
    ax.plot(90, 12350, 'ro', markersize=12, zorder=5)

    # 주석
    ax.annotate('매수', xy=(0, 10000), xytext=(-5, 9500), fontsize=9, color='green')
    ax.annotate('분할익절\n+3%', xy=(20, 10300), xytext=(10, 10800), fontsize=9, color='olive')
    ax.annotate('최고가\n13,000원\n(+30%)', xy=(60, 13000), xytext=(65, 13500), fontsize=9, ha='center')
    ax.annotate('Safety Lock!\n이격도 112%\n고점 -5%', xy=(90, 12350), xytext=(100, 12800),
                fontsize=9, ha='center', color='red',
                arrowprops=dict(arrowstyle='->', color='red'))

    # 고점 대비 -5% 표시
    ax.axhline(y=13000*0.95, color='red', linestyle='--', alpha=0.5, xmin=0.4, xmax=0.8)
    ax.text(75, 12400, '고점 -5%', fontsize=8, color='red')

    ax.set_xlim(-5, 155)
    ax.set_ylim(9000, 14500)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 B: 급등 후 급락 (Safety Lock 발동)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    result_text = "결과: 분할익절 +3% (50주) + Safety Lock +23.5% (50주) = 평균 +13.25%"
    ax.text(75, 9300, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_b_safety_lock.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_b_safety_lock.png 생성 완료")


def create_scenario_c():
    """시나리오 C: 급락 (Crash Guard 발동)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    times = np.linspace(0, 80, 120)

    # 가격: 상승 후 급락
    price = 10000 + np.concatenate([
        np.linspace(0, 300, 25),      # +3%
        np.linspace(300, 1000, 25),   # 고점
        np.linspace(1000, -300, 70)   # 급락
    ])

    # EMA20 (천천히 따라감)
    ema20 = np.full(120, 10000)

    entry_price = 10000
    crash_guard = entry_price * 0.98  # EMA20 * 0.98

    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.axhline(y=10000, color='orange', linestyle='--', linewidth=1.5, label='EMA20 (10,000원)')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가')
    ax.axhline(y=crash_guard, color='purple', linestyle='--', linewidth=1.5, label='Crash Guard (EMA20×0.98)')
    ax.axhline(y=entry_price * 0.965, color='darkred', linestyle='-', alpha=0.5, label='Safety Net (-3.5%)')

    # 마커
    ax.plot(0, 10000, 'go', markersize=12, zorder=5)
    ax.plot(25, 10300, 'yo', markersize=12, zorder=5)
    ax.plot(50, 11000, 'b^', markersize=10, zorder=5)

    # Crash Guard 발동 지점
    crash_idx = np.where(price < crash_guard)[0]
    if len(crash_idx) > 0:
        crash_point = crash_idx[0]
        ax.plot(times[crash_point], price[crash_point], 'ro', markersize=12, zorder=5)
        ax.annotate('Crash Guard!\n즉시 청산', xy=(times[crash_point], price[crash_point]),
                    xytext=(times[crash_point]+10, price[crash_point]+300),
                    fontsize=9, color='red', ha='center',
                    arrowprops=dict(arrowstyle='->', color='red'))

    ax.annotate('매수', xy=(0, 10000), xytext=(-5, 9700), fontsize=9, color='green')
    ax.annotate('분할익절', xy=(25, 10300), xytext=(20, 10600), fontsize=9, color='olive')
    ax.annotate('최고가\n11,000원', xy=(50, 11000), xytext=(55, 11300), fontsize=9)

    ax.set_xlim(-5, 85)
    ax.set_ylim(9400, 11500)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 C: 급락 (Crash Guard 발동)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)

    result_text = "결과: 분할익절 +3% (50주) + Crash Guard -2% (50주) = 평균 +0.5%"
    ax.text(40, 9500, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_c_crash_guard.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_c_crash_guard.png 생성 완료")


def create_scenario_d():
    """시나리오 D: 매수 직후 하락 (Floor Line 손절)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    times = np.linspace(0, 50, 80)

    # 가격: 매수 후 바로 하락
    price = 10000 + np.concatenate([
        np.linspace(0, 50, 10),       # 약간 상승
        np.linspace(50, -200, 70)     # 하락
    ])

    entry_price = 10000
    floor_line = 9850
    safety_net = entry_price * 0.965

    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가 (10,000원)')
    ax.axhline(y=floor_line, color='red', linestyle='--', linewidth=2, label='Floor Line (9,850원, -1.5%)')
    ax.axhline(y=safety_net, color='darkred', linestyle='-', alpha=0.5, label='Safety Net (9,650원, -3.5%)')

    # 마커
    ax.plot(0, 10000, 'go', markersize=12, zorder=5)

    # Floor Line 이탈 지점
    floor_idx = np.where(price < floor_line)[0]
    if len(floor_idx) > 0:
        floor_point = floor_idx[0]
        ax.plot(times[floor_point], price[floor_point], 'ro', markersize=12, zorder=5)
        ax.annotate('Floor Line 이탈!\n기술적 손절', xy=(times[floor_point], price[floor_point]),
                    xytext=(times[floor_point]+8, price[floor_point]+100),
                    fontsize=9, color='red', ha='center',
                    arrowprops=dict(arrowstyle='->', color='red'))

    ax.annotate('매수\n10,000원', xy=(0, 10000), xytext=(-3, 10150), fontsize=9, color='green')

    # 설명 박스
    explanation = "분할익절 전이므로\nSafety Lock, Crash Guard,\nEMA20 이탈은 미작동"
    ax.text(35, 10100, explanation, fontsize=9, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))

    ax.set_xlim(-5, 55)
    ax.set_ylim(9550, 10300)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 D: 매수 직후 하락 (Floor Line 손절)', fontsize=14, fontweight='bold')
    ax.legend(loc='lower left', fontsize=9)
    ax.grid(True, alpha=0.3)

    result_text = "결과: Floor Line 손절 -1.5% ~ -2%"
    ax.text(25, 9600, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_d_floor_line.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_d_floor_line.png 생성 완료")


def create_scenario_e():
    """시나리오 E: VI 발동 (Safety Net만 작동)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    times = np.linspace(0, 100, 150)

    # 가격: 상승 후 VI 발동 중 급락
    price = 10000 + np.concatenate([
        np.linspace(0, 300, 25),      # +3%
        np.linspace(300, 1500, 25),   # 고점
        np.linspace(1500, -350, 100)  # VI 중 급락
    ])

    entry_price = 10000
    safety_net = entry_price * 0.965

    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가')
    ax.axhline(y=safety_net, color='darkred', linestyle='-', linewidth=2, label='Safety Net (-3.5%)')

    # VI 구간 표시
    vi_start, vi_end = 50, 90
    ax.axvspan(vi_start, vi_end, alpha=0.2, color='red', label='VI 발동 구간')
    ax.text((vi_start+vi_end)/2, 11200, 'VI 발동 구간\n(매도 로직 정지)',
            fontsize=10, ha='center', color='red', fontweight='bold')

    # 마커
    ax.plot(0, 10000, 'go', markersize=12, zorder=5)
    ax.plot(25, 10300, 'yo', markersize=12, zorder=5)
    ax.plot(50, 11500, 'b^', markersize=10, zorder=5)

    # Safety Net 발동 지점
    safety_idx = np.where(price < safety_net)[0]
    if len(safety_idx) > 0:
        safety_point = safety_idx[0]
        ax.plot(times[safety_point], price[safety_point], 'ro', markersize=12, zorder=5)
        ax.annotate('Safety Net 발동!\nVI 중에도 작동', xy=(times[safety_point], price[safety_point]),
                    xytext=(times[safety_point]+10, price[safety_point]+300),
                    fontsize=9, color='darkred', ha='center',
                    arrowprops=dict(arrowstyle='->', color='darkred'))

    ax.annotate('매수', xy=(0, 10000), xytext=(-5, 9700), fontsize=9, color='green')
    ax.annotate('분할익절', xy=(25, 10300), xytext=(20, 10600), fontsize=9, color='olive')
    ax.annotate('최고가', xy=(50, 11500), xytext=(45, 11800), fontsize=9)

    # VI 설명 박스
    vi_explanation = "VI 발동 시 정지:\n• Safety Lock\n• Crash Guard\n• EMA20 이탈\n• Floor Line\n\nVI 중에도 작동:\n• Safety Net (-3.5%)\n• 수동 /sell"
    ax.text(105, 10500, vi_explanation, fontsize=8, ha='left', va='center',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.9))

    ax.set_xlim(-5, 130)
    ax.set_ylim(9400, 12000)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 E: VI 발동 (Safety Net만 작동)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    result_text = "결과: VI 발동 중 급락 → Safety Net이 -3.5%에서 손실 제한"
    ax.text(50, 9500, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_e_vi_active.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_e_vi_active.png 생성 완료")


def create_scenario_f():
    """시나리오 F: 이상적 수익 (장기 트렌드 추종)"""
    fig, ax = plt.subplots(figsize=(12, 7))

    times = np.linspace(0, 150, 200)

    # 가격: 지속적인 상승 후 EMA 이탈
    price = 10000 + np.concatenate([
        np.linspace(0, 300, 25),      # +3%
        np.linspace(300, 2500, 125),  # 지속 상승
        np.linspace(2500, 2000, 50)   # 조정 후 EMA 이탈
    ])

    # EMA20 (가격 추종)
    ema20 = 10000 + np.concatenate([
        np.linspace(0, 150, 25),
        np.linspace(150, 2000, 125),
        np.linspace(2000, 2100, 50)
    ])

    entry_price = 10000

    ax.plot(times, price, 'b-', linewidth=2, label='가격')
    ax.plot(times, ema20, 'orange', linestyle='--', linewidth=1.5, label='EMA20')
    ax.axhline(y=entry_price, color='gray', linestyle='-', alpha=0.5, label='매수가')

    # 마커
    ax.plot(0, 10000, 'go', markersize=12, zorder=5)
    ax.plot(25, 10300, 'yo', markersize=12, zorder=5)
    ax.plot(150, 12500, 'b^', markersize=10, zorder=5)
    ax.plot(195, 12000, 'ro', markersize=12, zorder=5)

    ax.annotate('매수\n10,000원', xy=(0, 10000), xytext=(-5, 9600), fontsize=9, color='green')
    ax.annotate('분할익절\n+3% (50주)', xy=(25, 10300), xytext=(35, 10700), fontsize=9, color='olive')
    ax.annotate('최고가\n12,500원\n(+25%)', xy=(150, 12500), xytext=(155, 12900), fontsize=9)
    ax.annotate('EMA20 이탈\n청산 (+20%)', xy=(195, 12000), xytext=(170, 11500),
                fontsize=9, color='red', ha='center',
                arrowprops=dict(arrowstyle='->', color='red'))

    # 트렌드 추종 설명
    ax.annotate('', xy=(120, 12000), xytext=(40, 10500),
                arrowprops=dict(arrowstyle='->', color='blue', lw=2, ls='--'))
    ax.text(80, 11500, '추세 추종\n(EMA20 위에서 유지)', fontsize=9, ha='center', color='blue')

    ax.set_xlim(-5, 205)
    ax.set_ylim(9500, 13500)
    ax.set_xlabel('시간', fontsize=11)
    ax.set_ylabel('가격 (원)', fontsize=11)
    ax.set_title('시나리오 F: 이상적 수익 (장기 트렌드 추종)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper left', fontsize=9)
    ax.grid(True, alpha=0.3)

    result_text = "결과: 분할익절 +3% (50주) + EMA20청산 +20% (50주) = 평균 +11.5%"
    ax.text(100, 9700, result_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'scenario_f_ideal_profit.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] scenario_f_ideal_profit.png 생성 완료")


def create_exit_logic_overview():
    """청산 로직 전체 흐름도"""
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # 제목
    ax.text(50, 97, 'PRD v3.2 청산 로직 우선순위', fontsize=16, ha='center', fontweight='bold')

    # 박스들
    boxes = [
        (50, 85, '1. 분할 익절\n+3% → 50% 매도', 'lightgreen'),
        (50, 72, '2. Safety Lock\n이격도≥110% AND 고점-5%', 'lightblue'),
        (50, 59, '3. Crash Guard\n현재가 < EMA20×0.98', 'plum'),
        (50, 46, '4. 3분봉 EMA20 이탈\n봉 종가 < EMA20 (Wick Protection)', 'lightyellow'),
        (50, 33, '5. 기술적 손절\n현재가 < Floor Line', 'lightsalmon'),
        (50, 20, '6. Safety Net\n-3.5% 하드스탑', 'lightcoral'),
    ]

    for x, y, text, color in boxes:
        box = mpatches.FancyBboxPatch((x-20, y-5), 40, 10,
                                       boxstyle="round,pad=0.02",
                                       facecolor=color, edgecolor='black')
        ax.add_patch(box)
        ax.text(x, y, text, ha='center', va='center', fontsize=10)

    # 화살표
    for i in range(len(boxes)-1):
        ax.annotate('', xy=(50, boxes[i+1][1]+5), xytext=(50, boxes[i][1]-5),
                    arrowprops=dict(arrowstyle='->', color='gray', lw=2))

    # VI 설명
    vi_text = "VI 발동 시:\n정지: 2,3,4,5\n작동: 1,6"
    ax.text(85, 50, vi_text, fontsize=10, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightyellow', edgecolor='red', linewidth=2))

    # 분할익절 전/후 설명
    before_text = "분할익절 전:\n1,5,6만 작동"
    after_text = "분할익절 후:\n모두 작동"
    ax.text(15, 60, before_text, fontsize=9, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightgray'))
    ax.text(15, 45, after_text, fontsize=9, ha='center',
            bbox=dict(boxstyle='round', facecolor='lightgray'))

    plt.tight_layout()
    plt.savefig(SAVE_PATH / 'exit_logic_overview.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("[OK] exit_logic_overview.png 생성 완료")


if __name__ == "__main__":
    print("=" * 50)
    print("PRD v3.2 청산 로직 시나리오 차트 생성")
    print("=" * 50)

    create_scenario_a()
    create_scenario_b()
    create_scenario_c()
    create_scenario_d()
    create_scenario_e()
    create_scenario_f()
    create_exit_logic_overview()

    print("=" * 50)
    print(f"[OK] 모든 차트 생성 완료! 저장 위치: {SAVE_PATH}")
    print("=" * 50)
