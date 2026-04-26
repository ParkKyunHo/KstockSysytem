import time
from check_bal import fn_kt00001 as get_balance
from check_bid import fn_ka10004 as check_bid
from buy_stock import fn_kt10000 as buy_stock
from stock_info import fn_ka10001 as stock_info
from acc_val import fn_kt00004 as get_my_stocks
from tel_send import tel_send
from get_setting import get_setting
from login import fn_au10001 as get_token

def chk_n_buy(stk_cd, token=None):

	try:
		my_stocks = get_my_stocks(token=token)
		for stock in my_stocks:
			if stock['stk_cd'].replace('A', '') == stk_cd:
				print("이미 보유 중입니다.")
				return
	except Exception as e:
		print("보유종목 조회 중 오류 발생:", e)
		return

	time.sleep(0.3)

	try:
		balance = int(get_balance(token=token))
		if balance <= 0:
			print("잔고가 없습니다.")
			return
	except Exception as e:
		print("잔고 조회 중 오류 발생:", e)
		return

	buy_ratio = get_setting('buy_ratio', 5.0) / 100

	expense = balance * buy_ratio
	print('지출할 금액:', expense)

	time.sleep(0.3)

	try:
		bid = int(check_bid(stk_cd, token=token))
	except Exception as e:
		print("호가 조회 중 오류 발생:", e)
		return

	if bid > 0:
		ord_qty = int(expense // bid)  # 내림하여 정수로 변환
		if ord_qty == 0:
			print("주문할 주식 수량이 0입니다.")
			return
		print('주문할 주식 수량:', ord_qty)

	time.sleep(0.3)

	try:
		buy_result = buy_stock(stk_cd, ord_qty, bid, token=token)
		if buy_result != 0:
			print("주문 실패")
			return
	except Exception as e:
		print("주문 중 오류 발생:", e)
		return

	time.sleep(0.3)

	try:
		stock_name = stock_info(stk_cd, token=token)
	except Exception as e:
		print("종목정보 조회 중 오류 발생:", e)
		return

	message = f'{stock_name} {ord_qty}주 매수 완료'
	print(message)
	tel_send(message)

if __name__ == '__main__':
	chk_n_buy('005930', token=get_token())