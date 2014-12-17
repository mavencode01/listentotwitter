import time
import threading
import json

from tweepy.streaming import StreamListener
from tweepy import OAuthHandler
from tweepy import Stream

from listentotwitter.config import TWITTER_CONSUMER_KEY
from listentotwitter.config import TWITTER_CONSUMER_SECRET
from listentotwitter.config import TWITTER_ACCESS_TOKEN
from listentotwitter.config import TWITTER_ACCESS_TOKEN_SECRET
from listentotwitter.debug import log


class StreamHandler(StreamListener):
    
    def __init__(self, tweet_callback, first_response_callback = None):
        self._tweet_callback = tweet_callback
        self._first_response_callback = first_response_callback

        self._stop_signal = False
        self._first_response = True

    def on_connect(self):
        log("Twitter stream connected")
        if self._first_response:
            self._first_response = False
            if self._first_response_callback is not None:
                self._first_response_callback(True)

    def on_data(self, data):
        if self._stop_signal:
            return False

        datadict = json.loads(data)

        if 'in_reply_to_status_id' in datadict:
            tweet = datadict['text']
            self._tweet_callback(tweet)

    def on_error(self, status):
        log("Received Twitter API error: " + str(status))
        if self._first_response:
            self._first_response = False
            if self._first_response_callback is not None:
                self._first_response_callback(status)

        return not self._stop_signal

    def stop(self):
        self._stop_signal = True


class StreamThread(threading.Thread):

    def __init__(self, auth, keywords_tracking, tweet_callback, first_response_callback = None):
        threading.Thread.__init__(self)

        self._keywords_tracking = keywords_tracking
        self._first_response_callback = first_response_callback

        self._streamhandler = StreamHandler(tweet_callback, first_response_callback)
        self._stream = Stream(auth, self._streamhandler)

        self._stop_signal = False

    def get_keywords_tracking(self):
        return list(self._keywords_tracking)

    def run(self):
        log("Starting Twitter stream")
        while True:
            if self._stop_signal:
                break

            try:
                self._stream.filter(track=self._keywords_tracking)
                break
            except Exception:
                if self._streamhandler._first_response:
                    self._streamhandler._first_response = False
                    if self._first_response_callback is not None:
                        self._first_response_callback(False)

                continue

    def stop(self):
        log("Stopping Twitter stream")
        self._stop_signal = True
        self._streamhandler.stop()


class TweetStreamer():

    reconnect_interval = 10

    def __init__(self, tweet_callback):
        self._tweet_callback = tweet_callback

        self._auth = OAuthHandler(TWITTER_CONSUMER_KEY, TWITTER_CONSUMER_SECRET)
        self._auth.set_access_token(TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_TOKEN_SECRET)

        self._streamthread = None
        self._new_streamthead = None
        self._keywords_tracking = None
        self._update_keywords_tracking_locked = False
        self._last_connect = 0

    def _on_stream_first_response(self, response):
        if response is True:
            if self._streamthread is not None:
                self._streamthread.stop()
            self._streamthread = self._new_streamthread
            del self._new_streamthread
            self._new_streamthread = None
            self._update_keywords_tracking_locked = False

            if self._streamthread.get_keywords_tracking != self._keywords_tracking:
                self._update_keywords_tracking(self._keywords_tracking)
        else:
            self._new_streamthread.stop()
            self._new_streamthread = None
            self._update_keywords_tracking_locked = False
            self.update_keywords_tracking(self._keywords_tracking)

    def update_keywords_tracking(self, keywords_tracking):
        log("Updating keywords tracking to: " + ", ".join(keywords_tracking))
        self._keywords_tracking = keywords_tracking

        log("Update keywords tracking locked: " + str(self._update_keywords_tracking_locked))
        if self._update_keywords_tracking_locked:
            return

        self._update_keywords_tracking_locked = True

        connect_diff = time.time() - self._last_connect
        if self.reconnect_interval > connect_diff:
            log("Sleeping for " + str(connect_diff) + " before updating keywords tracking")
            time.sleep(connect_diff)

        self._new_streamthread = StreamThread(self._auth, self._keywords_tracking, self._tweet_callback, self._on_stream_first_response)
        self._last_connect = time.time()
        self._new_streamthread.start()
