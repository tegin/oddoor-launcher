import logging
import os
import time

import git
import github
import psutil
import RPi.GPIO as GPIO
from oddoor import Oddoor
from oot import OotAmqp
from packaging import version as packaging_version

_logger = logging.getLogger(__name__)

RELAY = 15
volume = 99
duration = 0.1
hz = 440
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(RELAY, GPIO.OUT)
GPIO.output(RELAY, GPIO.LOW)


def get_data_mfrc522(reader, **kwargs):
    time.sleep(5.0)
    while True:
        uid = reader.scan_card()
        if uid:
            return uid


def get_data_keypad(keypad, buzzer, **kwargs):
    time.sleep(1)
    text = ""
    pressed = False
    while True:
        key = keypad.getKey()
        if not key:
            pressed = False
        elif pressed:
            pass
        elif key == "#":
            if len(text) > 0:
                return text, {"force_key": True}
            buzzer.play([(volume, hz * 2, duration)])
        elif key == "*":
            text = ""
            buzzer.play([(volume, hz * 2, duration)])
        else:
            text += key
            buzzer.play([(volume, hz, duration)])
            pressed = True
        time.sleep(0.1)


class OddoorLauncher(Oddoor, OotAmqp):
    fields = {
        "force_key": {
            "name": "Static Key for Key Board",
            "placeHolder": "Key that must be a number",
        }
    }
    organization = "tegin"
    repo_name = "oddoor-launcher"

    def check_upgrade(self, **kwargs):
        g = github.Github()
        repo = g.get_organization(self.organization).get_repo(self.repo_name)
        release = repo.get_latest_release().tag_name
        if packaging_version.parse(self.version) < packaging_version.parse(release):
            self.upgrade_repository(release)

    def upgrade_repository(self, release):
        repo = git.Repo(self.path)
        repo.remote("origin").fetch()
        repo.git.checkout(release)
        self.reboot()

    def __init__(self, connection, rdr, keypad, buzzer, version, path):
        super().__init__(connection)
        self.keypad = keypad
        self.buzzer = buzzer
        self.reader = rdr
        self.version = version
        self.path = path
        self.functions = [
            [get_data_mfrc522, self.reader],
            [get_data_keypad, self.keypad, self.buzzer],
        ]

    def get_default_amqp_options(self):
        res = super().get_default_amqp_options()
        res["open"] = self.amqp_key_check(self.open_force)
        res["upgrade"] = self.amqp_key_check(self.check_upgrade)
        return res

    def open_force(self, **kwargs):
        _logger.info(
            (self.connection_data.get("force_key", False), {"force_key": True})
        )
        self.queue.put(
            (self.connection_data.get("force_key", False), {"force_key": True})
        )

    @staticmethod
    def start_execute_function(function, *args, queue=False, **kwargs):
        p = psutil.Process(os.getpid())
        # set to lowest priority, this is windows only, on Unix use ps.nice(19)
        p.nice(6)

    def no_key(self, **kwargs):
        time.sleep(0.5)

    def check_key(self, key, **kwargs):
        if kwargs.get("force_key", False):
            return {
                "access_granted": key == self.connection_data.get("force_key", False)
            }
        return super().check_key(key, **kwargs)

    def access_granted(self, key, **kwargs):
        GPIO.output(RELAY, GPIO.HIGH)
        self.buzzer.play([(volume, hz, duration), (volume, hz * 1.28, duration)])
        time.sleep(1)
        GPIO.output(RELAY, GPIO.LOW)

    def access_rejected(self, key, **kwargs):
        self.buzzer.play([(volume, hz * 1.26, duration), (volume, hz, duration)])
        time.sleep(1)

    def exit(self, **kwargs):
        self.keypad.exit()
        GPIO.cleanup()
