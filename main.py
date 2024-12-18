from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import datetime
import time
import argparse
from collections import defaultdict
from email.mime.text import MIMEText
from email.header import Header
import smtplib
from smtplib import SMTP
import logging
import schedule

# 保存log信息
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("./booking.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
# 启用详细日志
capabilities = DesiredCapabilities.CHROME
capabilities["goog:loggingPrefs"] = {"driver": "ALL", "browser": "ALL"}

# 配置选项
LOGIN_URL = r"https://ids.xmu.edu.cn/authserver/login?type=userNameLogin&service=http%3A%2F%2Fcgyy.xmu.edu.cn%2Fidcallback"
BOOKING_URL = r"https://cgyy.xmu.edu.cn"
SHOW_BOOKING = r"https://cgyy.xmu.edu.cn/my_reservations"
ROOM = "2" # 默认是健身房
USERNAME = "**********" # 学号
PASSWORD = "**********" # 密码
TELEPHONE = "**********" # 手机号
TARGET_TIMES_1 = ["10:30-12:00", "12:00-13:30", "13:30-15:00", "15:00-16:30", "16:30-18:00", "18:00-19:30", "19:30-21:00"] # 健身房
TARGET_TIMES_2 = ["12:00-14:00", "09:30-11:00", "14:30-16:00", "16:30-18:00", "18:30-20:30"] # 游泳馆
MAX_RETRIES = 10  # 最大重试次数
EMAIL_SENDER = '**********'  #发送邮箱
EMAIL_PASSWORD = '**********' # 邮箱密码 qq邮箱生成
EMAIL_RECEIVERS = ['**********']   # 接受邮箱


def init_driver():
    # ChromeDriver 的路径
    driver_path = "/Users/charleslc/Desktop/Projects/Code/GymEase/chromedriver-mac-arm64/chromedriver"
    # 设置 ChromeOptions
    options = Options()
    # 指定 Chrome 的二进制文件路径
    options.binary_location = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    # 初始化 Service
    service = Service(driver_path)
    # 启动 WebDriver
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def login(driver):
    driver.get(LOGIN_URL)
    try:
        # 等待用户名输入框加载
        password_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        print("Is Displayed:", password_element.is_displayed())
        print("Is Enabled:", password_element.is_enabled())
        print("Outer HTML:", password_element.get_attribute("outerHTML"))

        # 用户名
        user_input = driver.find_element(By.NAME, "username")
        user_input.send_keys(USERNAME)
        # 密码
        password_input = driver.find_element(By.NAME, "passwordText")
        password_input.send_keys(PASSWORD)
        # 确认点击
        login_click = driver.find_element(By.ID, "login_submit")
        login_click.click()
        time.sleep(5)
        print("登录成功")
    except Exception as e:
        print("登录失败:", e)

def book_facility(driver, room, start_days, end_days):
    """
    预约逻辑: 
    1. 选定预约的时间, 从今天开始+7天开始遍历, 时间按照TARGET_TIMES遍历，选出所有能预约的时间。
    2. 优先级是天数高于时间段，即确保尽早能预约上。
    """
    if room == "1":
        book_url = BOOKING_URL + "/room/1" # 健身房
        target_times = TARGET_TIMES_1
        room_string = "健身房"
    else:
        book_url = BOOKING_URL + "/room/2" # 游泳馆
        target_times = TARGET_TIMES_2
        room_string = "游泳馆"

    driver.get(book_url)
    # 预约时间
    target_dates = [(datetime.date.today() + datetime.timedelta(days=day)).strftime("%Y-%m-%d") for day in range(start_days, end_days)]
    # print("Attempting to book for date:", target_date)
    for target_date in target_dates:
        time_elements = []
        for time_slot in target_times:
            xpath_query = f"//span[contains(@class, 'date-info') and contains(text(), '{target_date}')]/../span[contains(@class, 'time-slot') and .//a[contains(text(), '{time_slot}')]]"
            time_elements = driver.find_elements(By.XPATH, xpath_query)
            if time_elements:
                try:
                    slot_link = time_elements[0].find_element(By.TAG_NAME, "a").get_attribute("href")
                    driver.get(slot_link)
                    telephone_input = driver.find_element(By.ID, "edit-field-tel-und-0-value")
                    telephone_input.send_keys(TELEPHONE)
                    submit_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.ID, "edit-submit"))
                    )
                    submit_button.click()
                    print(f"预约成功: 日期 {target_date}, 时间段 {time_slot}")
                    logging.info(f"预约成功: {room_string} 日期 {target_date}, 时间段 {time_slot}")
                    return f"{room_string} 预约成功: 日期 {target_date}, 时间段 {time_slot}"
                except Exception as e:
                    print(f"预约失败: 日期 {target_date}, 时间段 {time_slot}")
                    logging.error(f"预约失败: {room_string} 日期 {target_date}, 时间段 {time_slot} - 错误: {e}")
                    continue
    return None

def re_login():
    logging.info("重试前重新登录")
    driver.quit()  # 退出当前会话
    driver = init_driver()  # 重新初始化driver
    login(driver)  # 重新登录

    return driver
    

# 兜底任务，每天下午3点尝试预约
def retry_booking_with_login(driver, room, start_days, end_days, max_retries=MAX_RETRIES, base_delay=20):
    """
    重新登录并尝试预约。如果最大重试次数失败，发送失败通知，并安排下午3点的兜底重试任务。
    """
    logging.info("兜底任务开始，尝试预约!!!")
    for i in range(max_retries):
        logging.info(f"第 {i+1} 次尝试预约")
        
        result = book_facility(driver, room, start_days, end_days)
        if result:
            Send_email(f"{datetime.date.today().strftime('%Y-%m-%d')} 预约成功提醒", result, EMAIL_RECEIVERS)
            logging.info("预约成功，停止重试")
            return
        else:
            logging.warning(f"第 {i+1} 次预约失败，等待 {base_delay * (2 ** i)} 秒后重试")
            time.sleep(base_delay * (2 ** i))  # 指数退避

def book_with_fallback(driver, room, start_days, end_days):
    logging.info("======安排了下午3点的兜底重试任务========")
    driver = re_login()
    schedule.every().day.at("15:00").do(retry_booking_with_login, driver, room, start_days, end_days)
    logging.info("======安排了下午5点的兜底重试任务========")
    driver = re_login()
    schedule.every().day.at("17:00").do(retry_booking_with_login, driver, room, start_days, end_days)


def show_bookings(driver, room):
    """展示已预约的内容"""
    driver.get(f"{SHOW_BOOKING}/slot{room}")
    print("预约信息加载成功")

def Send_email(subject, email_text,receivers):
    sender = '1411279054@qq.com'
    #【接受者邮箱】
    receivers = receivers
    #【邮件内容】
    message = MIMEText(email_text, 'plain', 'utf-8')
    #【发件人】
    message['From'] = sender  
    #【收件人】
    message['To'] = ", ".join(receivers)
    #【邮件主题】
    message['Subject'] = Header(subject, 'utf-8')
    smtper = smtplib.SMTP('smtp.qq.com', 587)
    smtper.starttls() 
    smtper.login(sender, 'bqfdlqgpoqfzjiba')
    smtper.sendmail(sender, receivers, message.as_string())
    print('邮件发送完成!')
    

def main():
    # 参数解析
    parser = argparse.ArgumentParser(description="自动预约脚本")
    parser.add_argument("--room", type=str, choices=["1", "2"], default="1", help="房间编号: 1=健身房, 2=游泳馆")
    parser.add_argument("--start_days", type=int, default=0, help="预约开始日期(默认: 1天)")
    parser.add_argument("--end_days", type=int, default=7, help="预约天数范围 (默认: 7天)")
    parser.add_argument("--start_time", type=str, default="13:01", help="预约开始时间 (格式: HH:MM)")
    args = parser.parse_args()
    try:
        # 登录
        driver = init_driver()
        login(driver)
        # 等到开始时间再预约
        while datetime.datetime.now().strftime("%H:%M") < args.start_time:
            time.sleep(1)
        # 开始首次预约
        result = book_facility(driver, args.room, args.start_days, args.end_days)
        time.sleep(5)
        if result:
            Send_email(f"{datetime.date.today().strftime('%Y-%m-%d')} 预约成功提醒", result, EMAIL_RECEIVERS)
            logging.info("预约成功，脚本结束")
        else:
            logging.info("首次预约失败，再次尝试预约")
            # 再次尝试预约
            success = False
            for i in range(MAX_RETRIES):
                print(f"第{i+1}次尝试预约")
                result = book_facility(driver, args.room, args.start_days, args.end_days)
                if result:
                    Send_email(f"{datetime.date.today().strftime('%Y-%m-%d')} 预约成功提醒", result, EMAIL_RECEIVERS)
                    success = True
                    break
                else:
                    logging.warning(f"第 {i+1} 次预约失败，等待 60 秒后重试")
                    time.sleep(60)
            if not success:
                 # 兜底逻辑，再次尝试预约
                logging.error("所有重试失败，兜底再次预约")
                book_with_fallback(driver, args.room, args.start_days, args.end_days)
                Send_email(f"{datetime.date.today().strftime('%Y-%m-%d')} 预约失败提醒", "尝试多次仍未成功预约，请手动检查", EMAIL_RECEIVERS)
    except Exception as e:
        logging.error(f"发生错误: {e}")
        Send_email("预约脚本错误提醒", f"发生错误: {e}", EMAIL_RECEIVERS)
    finally:
        driver.quit()

if __name__ == "__main__":
    
    main()

