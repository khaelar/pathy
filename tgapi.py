import requests, json, re, io
import util
from pathlib import Path
from hashlib import md5
from const import *
from hashmapdb import singleton as hashmapdb

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
		util.log(f"Failed to delete msg {chat_id}/{msg_id}",
			err=True, send_tg=True)
		return False

def download_url_proxied(url, dest=None, use_cache=True):
	file_bytes = hashmapdb.get(f"file:url:{url}")
	if not use_cache or not file_bytes:
		sent_msg = send_message(DL_PROXY_CHAT_ID,
			f"Downloading {url}", file_url=url)
		file_id = sent_msg["document"]["file_id"]
		
		tg_file = call("getFile", {"file_id": file_id})
		tg_url = f"https://api.telegram.org/file/bot" \
			f"{BOT_TOKEN}/{tg_file['file_path']}"
		
		resp = requests.get(tg_url, allow_redirects=True)
		file_bytes = resp.content
		
		if use_cache:
			hashmapdb.add(f"file:url:{url}", file_bytes)
	
	if not dest:
		return file_bytes
	Path(dest).write_bytes(file_bytes)

def send_message(chat_id, text="", as_html=False, file_path=None, file_id=None,
		file_url=None, file_bytes=None, file_type="document", use_cache=True,
		**params):
	
	if len([p for p in [file_path, file_id, file_url, file_bytes] if p]) > 1:
		raise ValueError("Only one of file_path, file_id, "
			"file_url, file_bytes can be specified at the same time")
	
	cache_key = None
	_key = lambda dtype, body: f"id:{dtype}:{file_type}:{body}"
	if use_cache:
		if file_url: cache_key = _key(
			"url", file_url)
		elif file_path: cache_key = _key(
			"path", str(Path(file_path).resolve()))
		elif file_bytes: cache_key = _key(
			"bytes", md5(file_bytes).hexdigest())
			
	if cache_key:
		file_id = hashmapdb.get(cache_key, str)
		if file_id:
			file_path = file_url = file_bytes = None
	
	sent_msg = _send_message(chat_id, text, as_html, file_path,
		file_id, file_url, file_bytes, file_type, **params)
	
	if cache_key:
		file_id = _get_msg_file_id(sent_msg)
		if file_id:
			hashmapdb.add(cache_key, file_id)
	
	return sent_msg

def _send_message(chat_id, text="", as_html=False, file_path=None,
		file_id=None, file_url=None, file_bytes=None, file_type="document",
		**params):
	"Sends message without using any cache"
	
	params["chat_id"] = int(chat_id)
	if as_html: params["parse_mode"] = "HTML"
	
	if any([file_path, file_id, file_url, file_bytes]):
		method = f"send{util.ucfirst(file_type)}"
		params["caption"] = text
		params[file_type.lower()] = file_id or file_url or "attach://file"
	else:
		method = "sendMessage"
		params["text"] = text
	
	file_io = io.BytesIO()
	if file_path: file_io = open(file_path, "rb")
	elif file_bytes: file_io = io.BytesIO(file_bytes)
	
	with file_io:
		sent_msg = call(method, params, files={"file": file_io})
	
	return sent_msg

def _get_msg_file_id(msg):
	file_props = ("animation", "audio", "document", "photo", "sticker",
		"video", "video_note", "voice")
	
	for prop in file_props:
		attachment = msg.get(prop)
		if not attachment:
			continue
		if isinstance(attachment, list):
			attachment = attachment[-1] # for multiple PhotoSizes
		return attachment.get("file_id")

def get_file_type(mime_type, force_type=None):
	applicable = ("document",)
	if mime_type in ("image/png", "image/jpeg", "image/webp"):
		applicable = ("photo", "document")
	elif mime_type in ("image/gif",):
		applicable = ("photo", "animation", "document")
	elif mime_type in ("video/mp4", "video/mpeg", "video/ogg", "video/webm"):
		applicable = ("video", "video_note", "animation", "document")
	elif mime_type in ("audio/mpeg",):
		applicable = ("audio", "voice", "document")
	
	return force_type if force_type in applicable else applicable[0]

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
	
	def reply(self, text, as_html=False, **kwargs):
		return send_message(self.chat_id, text, as_html=as_html, **kwargs)
	
	def is_debug_cmd(self):
		if not self.is_text_msg():
			return False
		return self.chat_id == DEBUG_CHAT_ID and \
		self.text.startswith("ctl ")
	
	def parse_debug_cmd(self):
		if not self.is_debug_cmd():
			return (None, None)
		
		cmd_arr = self.text.split(" ")
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
		msg_text = self.text
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
	
	def get_chat_title(self):
		if not self.is_text_msg():
			return None
		chat = self.data["message"]["chat"]
		return chat.get("title") or \
			f"{chat.get('first_name', '')} {chat.get('last_name', '')}"
	
	def format(self, as_html=False):
		_json = json.dumps(self.data, indent="\t")
		if as_html:
			resp = f"<pre>{util.sanitize_html(_json)}</pre>"
		else:
			resp = _json
		return resp