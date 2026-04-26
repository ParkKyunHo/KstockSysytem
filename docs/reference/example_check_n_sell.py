import time
from acc_val import fn_kt00004 as get_my_stocks
from sell_stock import fn_kt10001 as sell_stock
from tel_send import tel_send
from get_setting import cached_setting
from login import fn_au10001 as get_token

def chk_n_sell(token=None):

	# 익절 수익율(%) - 목표 수익율에 도달하면 매도
	TP_RATE = cached_setting('take_profit_rate', 10.0)
	# 손절 수익율(%) - 손실 한계에 도달하면 매도
	SL_RATE = cached_setting('stop_loss_rate', -10.0)

	try:
		my_stocks = get_my_stocks(token=token)
		if not my_stocks:
			print("보유 종목이 없습니다.")
			return True
			
		for stock in my_stocks:

			# pl_rt는 문자열이므로 float으로 변환하여 비교해야 함
			pl_rt = float(stock['pl_rt'])
			if pl_rt > TP_RATE or pl_rt < SL_RATE:
				time.sleep(0.5)
				sell_result = sell_stock(stock['stk_cd'].replace('A', ''), stock['rmnd_qty'], token=token)
				if sell_result != 0:
					print("매도 실패")
					return True

				result_type = "익절" if pl_rt > TP_RATE else "손절"
				result_emoji = "🔴" if pl_rt > TP_RATE else "🔵"
				message = f'{result_emoji} {stock["stk_nm"]} {int(stock["rmnd_qty"])}주 {result_type} 완료 (수익율: {pl_rt}%)'
				tel_send(message)
				print(message)

		return True  # 성공적으로 실행됨

	except Exception as e:
		print(f"오류 발생(chk_n_sell): {e}")
		return False  # 예외 발생으로 실패

if __name__ == "__main__":
	chk_n_sell(token=get_token())