import logging
import os
from datetime import datetime
from random import randrange
from time import sleep
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from slack_sdk import WebClient

load_dotenv()

URL = os.getenv("PRE_CAPTCHA_URL")
XPATH_TO_CONTINUE_LINK = os.getenv("XPATH_TO_CONTINUE_LINK")
XPATH_TO_CAPTCHA_INPUT = os.getenv("XPATH_TO_CAPTCHA_INPUT")
XPATH_TO_CAPTCHA_SUBMIT = os.getenv("XPATH_TO_CAPTCHA_SUBMIT")
XPATH_TO_CALENDAR_BUTTON = os.getenv("XPATH_TO_RIGHT_BUTTON_ON_CALENDAR")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL")
SLACK_IDS = os.getenv("SLACK_IDS")
REPLY_WAIT_TIME = int(os.getenv("REPLY_WAIT_TIME_SECONDS"))
CHECK_REPLY_EVERY = int(os.getenv("CHECK_REPLY_EVERY_SECONDS"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def delay_x_seconds(
    min: int = 0, sec: int = 2, random: bool = False, bypass: bool = False
) -> None:
    if bypass:
        return
    if random:
        min = randrange(0, 29)
        sec = randrange(0, 29)
    delay_seconds = (min * 60) + (sec)
    sleep(delay_seconds)


def split_slack_ids(ids_str: str) -> list:
    return list(map(str.strip, ids_str.split(",")))


def get_slack_client(token):
    return WebClient(token=token)


def generate_mentions(user_id_list: list) -> str:
    return " ".join(f"<@{user_id}>" for user_id in user_id_list)


def send_slack_message(client, channel_id: str, message: str) -> None:
    response = client.chat_postMessage(channel=channel_id, text=message)


def send_slack_photo(client, channel_id: str, filename: str, comment: str) -> None:
    response = client.files_upload_v2(
        file=filename, channel=channel_id, initial_comment=comment
    )


def get_captcha_response(client, channel_id: str, mentions_list: list) -> str | None:
    result = client.conversations_history(channel=channel_id, inclusive=True, limit=1)
    message = result["messages"][0]
    if message["user"] not in mentions_list:
        return None
    return message["text"]


def go_to_page_before_captcha(driver):
    try:
        continue_href = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, XPATH_TO_CONTINUE_LINK))
        )
    except Exception:
        return None
    continue_href.click()
    return driver


def wait_for_calendar_page(driver):
    try:
        calendar_right_button = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, XPATH_TO_CALENDAR_BUTTON))
        )
    except Exception:
        return None
    return driver


def get_screenshot(driver, now: datetime):
    now_str = now.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%d%b%Y_%H%M%S")
    filename = f"{now_str}.png"
    driver.execute_script("document.body.style.zoom='200%'")
    driver.save_screenshot(filename)
    return driver, filename


def enter_captcha_and_proceed(driver, captcha_value: str):
    captcha_input_field = driver.find_element(By.XPATH, XPATH_TO_CAPTCHA_INPUT)
    captcha_input_field.send_keys(captcha_value)
    delay_x_seconds(sec=randrange(3, 7))
    captcha_submit_button = driver.find_element(By.XPATH, XPATH_TO_CAPTCHA_SUBMIT)
    captcha_submit_button.click()
    return driver


def wait_time_not_elapsed(started_at, max_seconds):
    if (datetime.now() - started_at).seconds >= max_seconds:
        return False
    return True


def delete_files(filenames):
    removed = []
    for filename in filenames:
        try:
            os.remove(filename)
            removed.append(filename)
        except FileNotFoundError:
            pass  # nothing to do actually
    return list(set(filenames) - set(removed))


def main():
    logger.info(
        f"Config: will check every {CHECK_REPLY_EVERY}s in {REPLY_WAIT_TIME}s for a reply"
    )
    client = get_slack_client(SLACK_BOT_TOKEN)
    logger.info("Slack client generated")
    recipients = split_slack_ids(SLACK_IDS)
    logger.info(f"Slack mentions: {recipients}")
    user_mentions = generate_mentions(recipients)
    driver = webdriver.Chrome()
    logger.info("Chrome driver initialized")
    driver.get(URL)
    logger.info(f"Navigated to {URL}")
    driver = go_to_page_before_captcha(driver)
    logger.info("Now on captcha page")
    if driver is None:
        message = f"{user_mentions} Failed to go to page before captcha"
        send_slack_message(client, channel_id=SLACK_CHANNEL, message=message)
        return

    driver, captcha_filename = get_screenshot(driver, datetime.now())
    logger.info("Captcha screenshot taken")
    send_slack_photo(
        client,
        channel_id=SLACK_CHANNEL,
        filename=captcha_filename,
        comment=user_mentions,
    )
    logger.info("Captcha screenshot sent, waiting for reply")
    reply_wait_start = datetime.now()
    captcha = None
    while wait_time_not_elapsed(reply_wait_start, REPLY_WAIT_TIME):
        captcha = get_captcha_response(
            client, channel_id=SLACK_CHANNEL, mentions_list=recipients
        )
        if captcha is not None:
            break
        delay_x_seconds(sec=CHECK_REPLY_EVERY)
        logging.info("No response yet")

    logger.info(f"Wait time ended / reply was sent: {captcha}")
    if captcha is None:
        message = f"{user_mentions} Could not go past captcha page"
        send_slack_message(client, channel_id=SLACK_CHANNEL, message=message)
        return

    logger.info("Entering captcha and clicking submit")
    driver = enter_captcha_and_proceed(driver, captcha)

    logger.info("Waiting for calendar page")
    driver = wait_for_calendar_page(driver)

    driver, calendar_filename = get_screenshot(driver, datetime.now())
    logger.info("Calendar screenshot taken")
    send_slack_photo(
        client,
        channel_id=SLACK_CHANNEL,
        filename=calendar_filename,
        comment=user_mentions,
    )
    logger.info("Calendar screenshot sent, cleaning up used image files")
    not_deleted_files = delete_files([captcha_filename, calendar_filename])
    if not_deleted_files:
        message = f"These files were not deleted: {', '.join(not_deleted_files)}"
        send_slack_message(client, channel_id=SLACK_CHANNEL, message=message)

    driver.close()


if __name__ == "__main__":
    main()
