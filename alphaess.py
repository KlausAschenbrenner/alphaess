import os
import sys
import time
import aiohttp
import logging
import hashlib
import asyncio
from typing import Optional
from gpiozero import Button
from datetime import datetime
from PIL import Image,ImageDraw,ImageFont

logger = logging.getLogger(__name__)
libdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'lib')
picdir = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'pic')

# Global variables which stores the information from the inverter
current_power_production = 0
battery_level = 0
grid_power = 0
battery_power = 0
current_load = 0
power_generation = 0
output_to_grid = 0
input_from_grid = 0
current_datetime = datetime.now()

if os.path.exists(libdir):
    sys.path.append(libdir)

from waveshare_epd import epd2in7_V2

# Initialize the e-Paper screen
current_screen = 1
epd = epd2in7_V2.EPD()
epd.init()
epd.Clear()
epd.init_Fast()
font12 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 12)
font18 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 18)
font36 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 36)
font48 = ImageFont.truetype(os.path.join(picdir, 'Font.ttc'), 48)

class AlphaESSAPI:
    def __init__(self) -> None:
        # Open the configuration file
        with open('configuration.conf', 'r') as file:
            # Read the configuration options
            self.BASEURL = file.readline().strip()
            self.APPID = file.readline().strip()
            self.APPSECRET = file.readline().strip()
            self.SERIALNUMBER = file.readline().strip()
            self.sys_sn_list = None

    # private funciton, generate signature based on timestamp
    def __get_signature(self, timestamp) -> str:
        return str(hashlib.sha512((self.APPID + self.APPSECRET + timestamp).encode("ascii")).hexdigest())
    
    # private function, send a get request
    async def __get_request(self, path, params) -> Optional[dict]:
        timestamp = str(int(time.time()))
        url = f"{self.BASEURL}/{path}"
        sign = self.__get_signature(timestamp)
        headers = {"appId": self.APPID, "timeStamp": timestamp, "sign": sign}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return data
                else:
                    logger.error(f"Get request error: {resp.status} {data}")

    # private function, send a post request
    async def __post_request(self, path, params) -> Optional[dict]:
        timestamp = str(int(time.time()))
        url = f"{self.BASEURL}/{path}"
        sign = self.__get_signature(timestamp)
        headers = {"appId": self.APPID, "timeStamp": timestamp, "sign": sign}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=params) as resp:
                data = await resp.json()
                if resp.status == 200:
                    return data
                else:
                    logger.error(f"Post request error {resp.status} {data}")

    # get the list of ESS registered to the APPID and the relevant info
    # cobat, emsStatus, mbat, minv, poinv, popv, surplusCobat, sysSn, usCapacity
    async def get_ess_list(self) -> Optional[list]:
        path = "getEssList"
        params = {}
        r = await self.__get_request(path, params)
        # get ssn_list using r.data
        if r is not None:
            if r['code'] == 200:
                if type(r['data']) == list:
                    self.sys_sn_list = [item['sysSn'] for item in r['data']]
                    return r['data']
                else:
                    self.sys_sn_list = r['data']['sysSn']
                    return [r['data']]
            else:
                logger.error(f"Get ess list error: {r['code']} {r['msg']}")
        
    # get the latest power data for the specific ESS
    # returns a dict of pbat, pev, pgrid, pload, ppv, soc
    async def get_last_power_data(self) -> Optional[dict]:
        path = "getLastPowerData"
        params = {"sysSn": self.SERIALNUMBER}
        r = await self.__get_request(path, params)
        if r is not None:
            if r['code'] == 200:
                return r['data']
            else:
                logger.error(f"Get last power data error: {r['code']} {r['msg']}")   

    # get one day of energy eata for the specific ESS
    # return a list of dicts of energy data (probably, untested)
    async def get_one_date_energy(self, date):
        path = "getOneDateEnergyBySn"
        params = {"sysSn": self.SERIALNUMBER, "queryDate": date}
        r = await self.__get_request(path, params)
        if r is not None:
            if r['code'] == 200:
                return r['data']
            else:
                logger.error(f"Get one date energy by SN error: {r['code']} {r['msg']}")

    # get one day of power data for the specific ESS
    # return a list of dicts of power data (probably, untested)
    async def get_one_date_power_by_sn(self, sn, date):
        path = "getOneDayPowerBySn"
        params = {"sysSn": sn, "queryDate": date}
        r = await self.__get_request(path, params)
        if r is not None:
            if r['code'] == 200:
                return r['data']
            else:
                logger.error(f"Get one date power by SN error: {r['code']} {r['msg']}")

    # get the current charging settings for the specific ESS
    # returns a list of batHighCap, gridCharge, timeChae1, timeChae2, timeChaf1, timeChaf2, the relevant settings
    async def get_in_charge_config_info(self, sn) -> Optional[dict]:
        path = "getInChargeConfigInfo"
        params = {"sysSn": sn}
        r = await self.__get_request(path, params)
        if r is not None:
            if r['code'] == 200:
                return r['data']
            else:
                logger.error(f"Get in charge config info error: {r['code']} {r['msg']}")

    # get the current discharging settings for the specific ESS
    # return a list of batUseCap, ctrDis, timeDise1, timeDise2, timeDisf1, timeDisf2, the settings
    async def get_out_charge_config_info(self, sn) -> Optional[dict]:
        path = "getOutChargeConfigInfo"
        params = {"sysSn": sn}
        r = await self.__get_request(path, params)
        if r is not None:
            if r['code'] == 200:
                return r['data']
            else:
                logger.error(f"Get out charge config info error: {r['code']} {r['msg']}")

# Our main function, that polls regularily Alpha-ESS for the current power data.
# It outputs everything to the e-Paper display.
async def poll_alphaess() -> None:
    global current_power_production
    global battery_level
    global grid_power
    global battery_power
    global current_load
    global power_generation
    global output_to_grid
    global input_from_grid
    global current_datetime

    # Initialize the AlphaESS API interface
    alpha = AlphaESSAPI()

    while 1 == 1:
        try:
            # Retrieve the current power data
            current_power_data = await alpha.get_last_power_data()
            energy_stats = await alpha.get_one_date_energy(datetime.now().strftime("%Y-%m-%d"))
            current_power_production = current_power_data.get('ppv')
            battery_level = current_power_data.get('soc')
            grid_power = current_power_data.get('pgrid')
            battery_power = current_power_data.get('pbat')
            current_load = current_power_data.get('pload')
            power_generation = energy_stats.get('epv')
            output_to_grid = energy_stats.get('eOutput')
            input_from_grid = energy_stats.get('eInput')
            current_datetime = datetime.now()

        except:
            print("An error occurred.")

        # Print out everything to the console
        print_to_console()

        # Print out everything to the e-Paper display
        print_to_epaper()

        # Wait for 30 seconds, until the next inverter update
        time.sleep(30)

# Prints out the data from the inverter to the console
def print_to_console():
    # Print out the current date and time
    print(f"Current date and time: {current_datetime}")
    print("=================================================")

    # Print out the current power data
    print(f"Current power production: {current_power_production}")
    print(f"Current battery level: {battery_level}%")
    print(f"Current load: {current_load}")

    # Print out the battery information
    if battery_power < 0:
        print(f"Power to battery: {battery_power * -1}")
    else:
        print(f"Power from battery: {battery_power}")

    # Print out the grid power information
    if grid_power < 0:
        print(f"Power to grid: {grid_power * -1}")
    else:
        print(f"Power from grid: {grid_power}")

    # Print out today's energy statistics
    print(f"Today's power generation: {power_generation} kWh")
    print(f"Today's output to the grid: {output_to_grid} kWh")
    print(f"Today's input from the grid: {input_from_grid} kWh")
    print("")

# Prints out the data from the inverter to the e-Paper screen
def print_to_epaper():
    Himage = Image.new('1', (epd.height, epd.width), 255)
    draw = ImageDraw.Draw(Himage)

    if current_screen == 1:
        draw.text((10, 0), "P: " + str(current_power_production) + " w", font = font48, fill = 0)
        draw.text((10, 50), "L: " + str(current_load) + " w", font = font48, fill = 0)
        draw.text((10, 100), "B: " + str(battery_level) + "%", font = font48, fill = 0)
        draw.text((15, 160), "Last Update: " + str(datetime.now()), font = font12, fill = 0)
    if current_screen == 2:
        draw.text((10, 0), "Production: " + str(current_power_production) + " w", font = font18, fill = 0)
        draw.text((10, 20), "Battery: " + str(battery_level) + "%", font = font18, fill = 0)
        draw.text((10, 40), "Load: " + str(current_load) + " w", font = font18, fill = 0)

        if battery_power < 0:
            draw.text((10, 60), "Power to Battery: " + str(battery_power * -1) + " w", font = font18, fill = 0)
        else:
            draw.text((10, 60), "Power from Battery: " + str(battery_power) + " w", font = font18, fill = 0)
        
        if grid_power < 0:
            draw.text((10, 80), "Power to Grid: " + str(grid_power * -1) + " w", font = font18, fill = 0)
        else:
            draw.text((10, 80), "Power from Grid: " + str(grid_power) + " w", font = font18, fill = 0)

        draw.text((10, 110), "Power Generation: " + str(power_generation) + " kWh", font = font18, fill = 0)
        draw.text((10, 130), "Output to Grid: " + str(output_to_grid) + " kWh", font = font18, fill = 0)
        draw.text((10, 150), "Input from Grid: " + str(input_from_grid) + " kWh", font = font18, fill = 0)

    # Write everything to the screen
    epd.display_Base(epd.getbuffer(Himage))

# This button press switches to the 1st data screen
def first_button_handler():
    global current_screen
    current_screen = 1
    print_to_epaper()

# This button press switches to the 2nd data screen
def second_button_handler():
    global current_screen
    current_screen = 2
    print_to_epaper()

# The button handlers for the various data screens
first_button = Button(5)
second_button = Button(6)
first_button.when_pressed = first_button_handler
second_button.when_pressed = second_button_handler

if __name__ == "__main__":
    asyncio.run(poll_alphaess())