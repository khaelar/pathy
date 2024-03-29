from google.oauth2 import service_account
from googleapiclient.discovery import build
from const import *

cred_scopes = ["https://www.googleapis.com/auth/youtube.force-ssl"]
creds = service_account.Credentials.from_service_account_file(
	str(GDRIVE_SERVICE_CRED), scopes=cred_scopes)
service = build("youtube", "v3", credentials=creds)

def get_channel_videos(channel_id, published_after=None, max_results=50):
	videos = []
	next_page_token = None

	while True:
		request = service.search().list(
			part="snippet",
			channelId=channel_id,
			type="video",
			maxResults=min(max_results, 50),
			order="date",
			pageToken=next_page_token,
			publishedAfter=published_after
		)
		response = request.execute()
		
		for item in response["items"]:
			videos.append(item)
			
			if len(videos) >= max_results:
				break
		
		if len(videos) >= max_results:
			break
		
		next_page_token = response.get("nextPageToken")
		if not next_page_token:
			break
	
	return videos