import re
from pathlib import Path
from time import sleep

from nier import connect

CONFIG = Path("config/nier.yaml")

intent = {
    "component": {
        "package": "com.jingyao.easybike",
        "class": "com.hellobike.bundlelibrary.web.WebActivity",
    },
    "action": None,
    "data": None,
    "type": None,
    "package": None,
    "flags": 872415232,
    "categories": [],
    "extras": {
        "KEY_NEED_LOADING_TYPE": {"type": "null", "value": None},
        "statusBarDarkFont": {"type": "boolean", "value": False},
        "statusBarColor": {"type": "int", "value": 2131100674},
        "showProgressView": {"type": "boolean", "value": True},
        "url": {
            "type": "string",
            "value": "hellobike://hellobike.com/openWeb?webUrl=https%3A%2F%2Fm.hellobike.com%2FAppPlatformH5%2Flatest%2Findex.html%23%2Fbounty%3FrefreshComponentContent%3Dtrue%26linkSource%3Dcomponent%26strategyCode%3Dwelfare_component_content_wait_sign_v3%26hasSweepLight%3D0&widgetTemplateId=welfare_center&contentType=1&buttonName=40",
        },
        "style": {"type": "int", "value": 0},
        "key_interceptor_cancel_menu_text": {"type": "string", "value": ""},
        "KEY_NEED_LOADING_URL": {"type": "string", "value": ""},
        "KEY_NEED_LOADING_RESOURCE": {"type": "int", "value": 0},
        "key_interceptor_continue_menu_text": {"type": "string", "value": ""},
        "channel": {"type": "null", "value": None},
        "showTopbar": {"type": "boolean", "value": True},
        "hybridBehavior": {"type": "boolean", "value": False},
        "key_interceptor_content_text": {"type": "string", "value": ""},
        "key_interceptor_text": {"type": "string", "value": ""},
        "KEY_LAUNCH_FLAGS": {"type": "int", "value": 603979776},
    },
}

hello_bike_package = "com.jingyao.easybike"

coins_collcted = 0


def back_to_hello():
    phone.open_app(hello_bike_package)


def check_solved():
    spans = phone.screenshot().ocr()
    spanA = next((s for s in spans if "任务失败" in s.text.strip()), None)

    if spanA:
        # phone.tap(1404, 600)
        pass

    ui = phone.parse_uidump(prefer_webview=False)
    completion_filter = {
        "text": "任务完成，",
        "resource_id": "com.jingyao.easybike:id/tvAdRewardTip",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }
    reward_filter = {
        "resource_id": "com.jingyao.easybike:id/rewardCount",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }

    if not ui.match(**completion_filter) or not ui.match(**reward_filter):
        return False

    reward = ui.find(**reward_filter)
    if reward is None:
        return False

    print(f"Task complete, coins {reward.text}")

    global coins_collcted
    coins_collcted += int(reward.text[1:])

    close_filter = {
        "resource_id": "com.jingyao.easybike:id/ivClose",
        "class_name": "android.widget.ImageView",
        "tag": "node",
    }
    if ui.match(**close_filter):
        close = ui.find(**close_filter)
        if close is not None:
            phone.widget(close).click()

    return True


def check_double():
    ui = phone.parse_uidump(prefer_webview=False)
    double_filter = {
        "text": "翻倍领取",
        "resource_id": "com.jingyao.easybike:id/tvExchangeDoubleNextVideo",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }

    if ui.match(**double_filter):
        button = ui.find(**double_filter)
        if button is None or button.center is None:
            return False

        phone.tap(*button.center)
        sleep(1)
        ad_solver()
        check_solved()
        return True

    return False


def ad_solver():
    package = phone.current_activity().package

    if package != hello_bike_package:
        sleep(5)
        back_to_hello()
        if check_solved():
            return

    ui = phone.parse_uidump()
    skip_filter = {
        "resource_id": "com.jingyao.easybike:id/tobid_interstitial_skip_text",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }

    if ui.match(**skip_filter):
        skip = ui.find(**skip_filter)
        if skip is not None:
            if skip.text != "关闭":
                time = int(skip.text.split("|")[1])
                sleep(time + 2)

            if skip.center is not None:
                phone.tap(*skip.center)

    else:
        feedback_filter = {
            "text": "反馈",
            "resource_id": "feed",
            "class_name": "android.widget.TextView",
            "tag": "node",
        }
        ad_filter = {
            "text": "广告",
            "class_name": "android.widget.TextView",
            "tag": "node",
        }
        if ui.match(**feedback_filter) and ui.match(**ad_filter):
            print("Recognized ad UI.")

    if not check_double():
        check_solved()


def sign():
    ui = phone.parse_uidump()
    dialog_filter = {"text": re.compile(r"断签重新开始", re.IGNORECASE)}
    if not ui.match(**dialog_filter):
        return

    print("Detected sign in dialog.")

    signin_filter = {"text": "签到"}
    if not ui.match(**signin_filter):
        return

    print("Sign in available.")
    video_filter = {
        "text": re.compile(r"点击广告再领.*奖励金"),
        "resource_id": "com.jingyao.easybike:id/tvSignInClickWithAds",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }
    if not ui.match(**video_filter):
        return

    button = ui.find(**video_filter)
    if button is None or button.center is None:
        return

    phone.tap(*button.center)

    sleep(5)
    ad_solver()


def watch_videos():
    # while True:
    ui = phone.parse_uidump()
    video_filter = {
        "text": "看视频",
        "class_name": "android.widget.TextView",
        "tag": "node",
    }
    if not ui.match(**video_filter):
        return

    button = ui.find(**video_filter)
    if button is None or button.center is None:
        return

    print("Video tasks are available, trying...")
    phone.tap(*button.center)


with connect(CONFIG) as phone:
    # result = phone.start_intent(intent, root=True)
    # print('Activity launch:', 'succeeded' if result.success else 'failed')
    # sleep(5)
    # sign()
    # check_solved()
    watch_videos()
    # ad_solver()
    # check_double()
