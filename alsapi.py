import requests, time
import util
from util import log, get_err
from const import *

def _send_request(url, validate_fn=None, retries=3):
	for attempt in range(retries):
		util.cap_freq("als_api", 1)
		
		try:
			resp = requests.get(url, headers={"Authorization": MOZAM_API_KEY})
			
			try:
				resp.raise_for_status()
				resp_data = resp.json()
				if validate_fn:
					assert validate_fn(resp_data)
			except Exception as e:
				log(f"ALS API invalid resp:\n{resp.text}", err=True)
				raise e
			
			return resp_data
		except Exception as e:
			log(f"Failed to retrieve ALS API data (attempt #{attempt+1}):\n" +
				get_err(), err=True)
			time.sleep(1)
			if (attempt + 1) == retries:
				raise e

def get_player_stat(player_uid):
	url = f"https://api.mozambiquehe.re/bridge?version=5&platform=PC" \
		f"&uid={player_uid}&merge=true&removeMerged=true"
	return _send_request(url, lambda r: "global" in r and "realtime" in r)

def get_map_rotation():
	url = f"https://api.mozambiquehe.re/maprotation?version=5"
	return _send_request(url)

def get_craft_rotation():
	url = f"https://api.mozambiquehe.re/crafting"
	return _send_request(url)

def name_to_uid(player_name):
	url = f"https://api.mozambiquehe.re/nametouid" \
		f"?player={player_name}&platform=PC"
	resp = _send_request(url, lambda r: r.get("uid"))
	return resp["uid"]

class AlsApiError(Exception):
	pass