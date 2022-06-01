import time, datetime
import util, localtext, alsapi
from util import log
from const import *


class TrackedPlayer():
	def __init__(self, player_state):
		self.uid = player_state["uid"]
		self.state = player_state
		self.timeline = PlayerTimeline(self.uid)
	
	def serialize(self):
		return self.state
	
	def update(self):
		stat = alsapi.get_player_stat(self.uid)
		diff = self.timeline.consume_als_stat(stat)
	
	def get_session_start(self, before_time):
		session_max_break = 30 * 60 # 30 min
		
		last_online = None
		for time, legend, stat_name, stat_value in self.iter(reverse=True):
			if time > before_time:
				continue
			
			if last_online == None:
				# looking for went offline event
				if stat_name == "is_online" and stat_value == "1":
					last_online = time
			else:
				# looking for any event happened earlier than
				# session_max_break since player went offline
				# or went online event to reset state
				if stat_name == "is_online" and stat_value == "0":
					last_online = None
				elif time < (last_online - session_max_break):
					return last_online
			

class PlayerTimeline():
	def __init__(self, player_uid):
		self.player_uid = player_uid
		self.timeline_path = TIMELINE_DIR / f"{player_uid}.txt"
		self.cur_stats = {} # keys are tuples (legend_name or "_", stat_name)
		
		TIMELINE_DIR.mkdir(exist_ok=True)
		self.timeline_handle = self.timeline_path.open("a", encoding="utf-8")
		self.load()
	
	def load(self):
		self.cur_stats = {}
		
		if not self.timeline_path.exists():
			return
		
		for _, legend, stat_name, stat_value in self.iter():
			self.cur_stats[(legend, stat_name)] = stat_value
	
	def add_entry(self, timestamp, legend, stat_name, stat_value, flush=True):
		self.cur_stats[(legend, stat_name)] = str(stat_value)
		
		line = " ".join((
			str(timestamp),
			util.semiurlencode(str(legend)),
			util.semiurlencode(str(stat_name)),
			util.semiurlencode(str(stat_value))
		))
		
		self.timeline_handle.write(line + "\n")
		if flush:
			self.timeline_handle.flush()
	
	def iter(self, reverse=False):
		if reverse:
			iterator = util.reverse_readline(self.timeline_path)
		else:
			iterator = self.timeline_path.open("r")
		
		try:
			for line in iterator:
				entry = line.strip(" \r\n")
				entry_split = entry.split(" ")
				
				if not entry:
					continue
				
				def _log_invalid():
					log(f"Skipping invalid entry in" \
						f" {self.player_uid}.txt timeline: '{entry}'")
				
				if len(entry_split) != 4:
					_log_invalid()
					continue
				
				entry_split[0] = util.to_num(entry_split[0])
				entry_split[1] = util.semiurldecode(str(entry_split[1]))
				entry_split[2] = util.semiurldecode(str(entry_split[2]))
				entry_split[3] = util.semiurldecode(str(entry_split[3]))
				
				if entry_split[0] == None:
					_log_invalid()
					continue
				
				yield entry_split
		except GeneratorExit:
			iterator.close()
	
	def get_diff(self, start, end):
		diff_data = {}
		# (legend or "_", stat): (start_value, end_value)
		
		for time, legend, stat_name, stat_value in self.iter():
			if time > end:
				break
			
			key = (legend, stat_name)
			if not diff_data.get(key):
				diff_data[key] = (None, None)
			
			if time < start:
				diff_data[key][0] = stat_value
			
			elif start <= time <= end:
				if diff_data[key][0] == None:
					diff_data[key][0] = stat_value
				diff_data[key][1] = stat_value
		
		return TimelineDiff(diff_data)
	
	def consume_als_stat(self, player_stat):
		timestamp = int(datetime.datetime.utcnow().timestamp())
		diff_data = {}
		
		def _add(stat_name, stat_value, legend="_"):
			prev_value = self.cur_stats.get((legend, stat_name))
			new_value = str(stat_value)
			if prev_value == new_value:
				return
			
			# this value from api may deviate
			if stat_name == "state_since":
				if abs(int(prev_value or 0) - int(new_value)) < 20:
					return
			
			self.add_entry(timestamp, legend, stat_name, stat_value, False)
			diff_data[(legend, stat_name)] = (prev_value, new_value)
		
		_global = player_stat["global"]
		_realtime = player_stat["realtime"]
		
		_add("level",  _global["level"] + \
			_global["toNextLevelPercent"] / 100)
		
		# weird complicated logic due to strange api responses sometimes
		is_online = bool(
			_realtime["isOnline"] and (
				_realtime["currentState"] != "offline" or \
				_realtime["currentStateSinceTimestamp"] != -1
			)
		)
		_add("is_online", int(is_online))
		_add("cur_state", _realtime["currentState"])
		_add("state_since", _realtime["currentStateSinceTimestamp"])
		_add("is_banned", int(_global["bans"]["isActive"]))
		
		_add("br_rank_score",   _global["rank"]["rankScore"])
		_add("br_rank_div",     _global["rank"]["rankDiv"])
		_add("br_rank_top_pos", _global["rank"]["ladderPosPlatform"])
		_add("br_rank_name",    _global["rank"]["rankName"])
		
		_add("ar_rank_score",   _global["arena"]["rankScore"])
		_add("ar_rank_div",     _global["arena"]["rankDiv"])
		_add("ar_rank_top_pos", _global["arena"]["ladderPosPlatform"])
		_add("ar_rank_name",    _global["arena"]["rankName"])
		
		_add("name", _global["name"])
		selected_legend = player_stat["legends"]["selected"]["LegendName"]
		_add("legend", selected_legend)
		
		for tracker in player_stat["legends"]["selected"]["data"]:
			_add("tracker_" + tracker["key"],
				tracker["value"], selected_legend)
		
		self.timeline_handle.flush()
		return TimelineDiff(diff_data)
	
	def close(self):
		self.timeline_handle.close()
	
	def __del__(self):
		self.close()

class TimelineIterator():
	def __init__(self, player_uid, reverse=False):
		self.player_uid = player_uid
		self.timeline_path = TIMELINE_DIR / f"{player_uid}.txt"
		self.file_handle = self.timeline_path.open("r")
		self.ended = False
	
	def __iter__(self):
		return self
	
	def __next__(self):
		if self.ended:
			raise StopIteration
		
		line = self.file_handle.readline()
		if not line.endswith("\n"):
			self.ended = True
			self.file_handle.close()
		
		entry = line.strip(" \r\n")
		entry_split = entry.split(" ")
		
		if not entry:
			return self.__next__()
		
		def _skip():
			log(f"Skipping invalid entry in" \
				f" {self.player_uid}.txt timeline: '{entry}'")
			return self.__next__()
		
		if len(entry_split) != 4:
			return _skip()
		
		entry_split[0] = util.to_num(entry_split[0])
		entry_split[1] = util.semiurldecode(str(entry_split[1]))
		entry_split[2] = util.semiurldecode(str(entry_split[2]))
		entry_split[3] = util.semiurldecode(str(entry_split[3]))
		
		if entry_split[0] == None:
			return _skip()
		
		return entry_split

class TimelineDiff():
	def __init__(self, data):
		self.data = data