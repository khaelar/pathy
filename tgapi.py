import requests, json, re
import util
from pathlib import Path
from const import *

class TgBotApiError(Exception):
	pass

def call(method, params={}, files={}):
	resp = requests.post(
		f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
		data=params,
		files=files
	)
	tg_reply = json.loads(resp.text)
	
	if (not "result" in tg_reply) or (not tg_reply["ok"]) or (not resp.ok):
		raise TgBotApiError("result['ok'] == False:\n" \
			+ json.dumps(tg_reply, indent="\t"))
	
	return tg_reply["result"]

def delete_msg(chat_id, msg_id):
	try:
		deleted_resp = call("deleteMessage", {
			"chat_id": chat_id,
			"message_id": msg_id
		})
		return True
	except TgBotApiError:
		log(f"Failed to delete msg {chat_id}/{msg_id}", err=True, send_tg=True)
		return False

def download_url_proxied(url, dest):
	sent_msg = call("sendDocument",
		{
		"chat_id": DL_PROXY_CHAT_ID,
		"document": url,
		"caption": f"Caching {url}"
		})
	file_id = sent_msg["document"]["file_id"]
	
	tg_file = call("getFile", {"file_id": file_id})
	tg_url = f"https://api.telegram.org/file/bot" \
		f"{BOT_TOKEN}/{tg_file['file_path']}"
	
	resp = requests.get(tg_url, allow_redirects=True)
	open(dest, 'wb').write(resp.content)

class Update():
	def __init__(self, update_data):
		self.data = update_data
		self.chat_id = None
		self.from_id = None
		self.msg_id = None
		self.text = None
		self.reply_to = None
		
		if self.is_msg():
			self.chat_id = self.data["message"]["chat"]["id"]
			self.from_id = self.data["message"]["from"]["id"]
			self.msg_id = self.data["message"]["message_id"]
			self.text = self.data["message"].get("text") or \
				self.data["message"].get("caption")
			self.reply_to = self.data["message"].get("reply_to_message")
	
	@classmethod
	def from_raw_body(cls, body_raw):
		update_data = json.loads(body_raw.decode("utf-8"))
		return cls(update_data)
	
	def is_msg(self):
		return "message" in self.data
	
	def is_text_msg(self):
		if not self.is_msg():
			return False
		return "text" in self.data["message"]
	
	def is_whitelisted(self):
		return self.data["message"]["chat"]["id"] in ALLOWED_CHATS
	
	def reply(self, text, as_html=False, **kwargs):
		return call(
			"sendMessage",
			{
				"chat_id": self.data["message"]["chat"]["id"],
				"text": text,
				"parse_mode": "HTML" if as_html else None,
				**kwargs
			}
		)
	
	def reply_img(self, img_path, caption, as_html=False, **kwargs):
		img_path = Path(img_path)
		return call(
			"sendPhoto",
			{
				"chat_id": self.data["message"]["chat"]["id"],
				"photo": "attach://file",
				"caption": caption,
				"parse_mode": "HTML" if as_html else None,
				**kwargs
			},
			files={
				"file": img_path.open("rb")
			}
		)
	
	def reply_vid(self, vid_path, caption, as_html=False, **kwargs):
		vid_path = Path(vid_path)
		return call(
			"sendVideo",
			{
				"chat_id": self.data["message"]["chat"]["id"],
				"video": "attach://file",
				"caption": caption,
				"parse_mode": "HTML" if as_html else None,
				**kwargs
			},
			files={
				"file": vid_path.open("rb")
			}
		)
	
	def is_debug_cmd(self):
		if not self.is_text_msg():
			return False
		return self.data["message"]["chat"]["id"] == DEBUG_CHAT_ID and \
		self.data["message"]["text"].startswith("ctl ")
	
	def parse_debug_cmd(self):
		if not self.is_debug_cmd():
			return (None, None)
		
		cmd_arr = self.data["message"]["text"].split(" ")
		cmd = cmd_arr[1]
		args_raw = " ".join(cmd_arr[2:])
		if args_raw:
			args = json.loads(args_raw)
		else:
			args = {}
		
		return (cmd, args)
	
	def parse_bot_command(self):
		if not self.is_text_msg():
			return (None, None)
		msg_text = self.data["message"]["text"]
		command_search = re.findall(
			"^(/[a-zA-Z0-9_]+)(@[a-zA-Z0-9_]+){0,1}", msg_text)
		if not command_search:
			return (None, None)
		
		command = command_search[0][0]
		botmention = command_search[0][1]
		if botmention and (botmention.lower() != f"@{BOT_USERNAME.lower()}"):
			return (None, None)
		
		full_command_len = len(command) + len(botmention)
		params = msg_text[full_command_len:].strip()
		
		return (command, params)
	
	def format(self, as_html=False):
		_json = json.dumps(self.data, indent="\t")
		if as_html:
			resp = f"<pre>{util.sanitize_html(_json)}</pre>"
		else:
			resp = _json
		return resp