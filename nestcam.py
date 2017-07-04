#!/usr/bin/python
####!/cygdrive/c/Python27/python

"""Nest Cam Tool"""

#### TODO
#### * make all defaults be in the 'config' dict and get overwritten
####   by cmdline opts
#### * make all/many config values be setable via cmd line opts
#### * enable logging and put logs into the code (instead of prints)
#### * make the get/set camera capabilities methods work
#### * restrict testing mode and do all prints with logs
#### * figure out notifications and add them -- including which devices are getting notifications from a camera
#### * figure out how to get clips from camera (if possible without the service)
#### * figure out how to get events from camera (if possible without the service),
####   including motion and sound events


import argparse
from datetime import datetime
import glob
import json
import os
import requests
import sys
import time
import yaml


# default configuraton
config = {
    "testing": True,
    "delay": 10 * 60,   # 10 mins
    "maxFrames": 10,    # keep last 10 frames
    "numFrames": 0,	    # capture forever
    "outPath": "/tmp/imgs/"  # save frames in /tmp/imgs/<camName>/<time>.jpg
}


DROPCAM_BASE = "https://www.dropcam.com/"
DROPCAM_PREFIX = os.path.join(DROPCAM_BASE, "api/v1/")


# Merge a new dict into an old one, updating the old one (recursively).
def dictMerge(old, new):
    for k, v in new.iteritems():
        if (k in old and isinstance(old[k], dict) and
            isinstance(new[k], collections.Mapping)):
            dictMerge(old[k], new[k])
        else:
            old[k] = new[k]


# Encapsulation of a Nest Camera
class Camera(object):
    def __init__(self, cookies, info):
        self.cookies = cookies
        self.info = info
        self.uuid = info['uuid']

    def name(self):
        return self.info['name']

    def id(self):
        return self.info['id']

    def capabilities(self):
        return self.info['capabilities']

    #### TODO add methods to get/set camera properties

    def dump(self):
        print("Camera: {0} - {1}".format(self.info['name'], self.info['uuid']))
        json.dump(self.info, sys.stdout, indent=4, sort_keys=True)
        print("\n")

    #### TODO method to grab a frame -- on event, periodically, log to file,...
    #### TODO figure out what to do with the seconds arg
    ####      (i.e.,: when to capture image in seconds from epoch)
    #### TODO figure out if we can specify image height too/instead of width?
    def grabFrame(self, width=720):
        path = "https://nexusapi.camera.home.nest.com/get_image"
        params = "uuid={0}&width={1}".format(self.uuid, width)
        r = requests.get(path, params=params, cookies=self.cookies)
        r.raise_for_status()

        if config['testing']:
            print("Headers: {0}".format(r.headers))
        if r.headers['content-length'] == 0:
            # got empty image with success code, so throw an exception
            raise ConnectionError('Unable to get image from camera')
        image = r.content
        return image

    #### TODO methods for events -- get last, wait for, log, etc.
    def getEvents(self, startTime, endTime=None):
        if not endTime:
            endTime = int(time.time())
        path = "https://nexusapi.camera.home.nest.com/get_cuepoint"
        params = "uuid={0}&start_time={1}&end_time={2}".format(self.uuid,
                                                               startTime,
                                                               endTime)
        r = requests.get(path, params=params, cookies=self.cookies)
        r.raise_for_status()
        print("RESPONSE: {0}\n".format(r))
        return r.json()

    #### TODO methods for events -- get last, wait for, log, etc.


# Encapsulation of the cameras and structures associated with a Nest account
class NestCam(object):
    @staticmethod
    def _err(msg, fatal=False):
        sys.stderr.write("Error: %s\n", msg)
        if fatal:
            sys.exit(1)

    def __init__(self, user, passwd, cameraIds):
        self.camIds = cameraIds

        # login to the NestCam API server
        path = DROPCAM_PREFIX + "login.login"
        hdrs = {'Referer': DROPCAM_BASE}
        body = {'username': user, 'password': passwd}
        r = requests.post(path, data=body, headers=hdrs)
        if r.status_code != requests.codes.ok:
            r.raise_for_status()
            NestCam._err("Unable to login: {0}".format(r.text), True)
        self.cookies = {k: v for k, v in r.cookies.items() if k == 'website_2'}
        resp = json.loads(r.text)['items'][0]
        self.accessToken = resp['nest_access_token']
        self.sessionToken = resp['session_token']
        if config['testing']:
            print("Cookies: {0}".format(r.cookies))
            print("Access Token: {0}".format(self.accessToken))
            print("Session Token: {0}".format(self.sessionToken))

        # instantiate objects for all of the requested cameras
        path = DROPCAM_PREFIX + "cameras.get_visible"
        body = {'group_cameras': True}
        r = requests.get(path, body, cookies=self.cookies)
        cams = r.json()['items'][0]['owned']
        self.cams = {}
        for cam in cams:
            cid = cam['uuid']
            if cid in self.camIds:
                self.cams[cid] = Camera(self.cookies, cam)

    def cameras(self):
        return self.cams.values()

    def cameraNames(self):
        return [self.cams[c].info['name'] for c in self.cams]

    def cameraIds(self):
        return self.cams.keys()

    def camerasMap(self):
        cams = {}
        for camId in self.cameraIds():
            cams[camId] = self.cams[camId].info['name']
        return cams

    '''
    def getCameraInfo(self, camId):
        if camId not in self.cameras:
            NestCam._err("Invalid camera id: {0}".format(camId))
            return None
        return self.cameras[camId].info

    def printCameraInfo(self, camId):
        info = self.getCameraInfo(camId)
        json.dump(info, sys.stdout, indent=4, sort_keys=True)
    '''


#
# MAIN
#
def main():
    # Print error and exit
    def fatalError(msg):
        sys.stderr.write("Error: {0}\n".format(msg))
        sys.stderr.write("Usage: {0}\n".format(usage))
        sys.exit(1)

    usage = sys.argv[0] + "[-v] [-n <names>] [-c <confFile>] " + \
        "[-d <secs>] [-u <username>] [-p <passwd>] " + \
        "[-f <numFrames>] [-m <maxFrames>] [-o <outPath>]"
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '-n', '--names', action='store', type=str,
        help="comma-separated list of camera names")
    ap.add_argument(
        '-d', '--delay', action='store', type=int,
        help="number of seconds to delay between sets of image grabs")
    ap.add_argument(
        '-f', '--numFrames', action='store', type=int,
        help="number of frames to capture (0=infinite)")
    ap.add_argument(
        '-m', '--maxFrames', action='store', type=int,
        help="maximum number of frames to save")
    ap.add_argument(
        '-o', '--outPath', action='store', type=str,
        help="path to directory where image grabs are to be written")
    ap.add_argument(
        '-u', '--user', action='store', type=str,
        help="user name")
    ap.add_argument(
        '-p', '--passwd', action='store', type=str,
        help="password")
    ap.add_argument(
        '-v', '--verbose', action='count', default=0,
        help="increase verbosity")
    ap.add_argument(
        '-c', '--configFile', action='store',
        help="configuration input file path (defaults to './nestcam.conf'")
    options = ap.parse_args()

    # get the config file and merge with the defaults
    confFilePath = None
    if options.configFile:
        if not os.path.isfile(options.configFile):
            sys.stderr.write("Error: config file not found\n")
            sys.exit(1)
        confFilePath = options.configFile
    else:
        defaultPath = "./nestcam.conf"
        if os.path.isfile(defaultPath):
            confFilePath = defaultPath
        else:
            sys.stderr.write("Error: config file '%s' not found\n",
                             defaultPath)
            sys.exit(1)
    if confFilePath is not None:
        with open(confFilePath, 'r') as ymlFile:
            confFile = yaml.load(ymlFile)
        dictMerge(config, confFile)

    # overwrite values from defaults and config file with cmd line options
    if options.user:
        config['user'] = options.user
    if options.passwd:
        config['passwd'] = options.passwd
    if options.delay:
        config['delay'] = options.delay
    if options.numFrames:
        config['numFrames'] = options.numFrames
    if options.maxFrames:
        config['maxFrames'] = options.maxFrames
    if options.outPath:
        config['outPath'] = options.outPath
    if options.verbose > 1:
        print("Configuration:")
        json.dump(config, sys.stdout, indent=4, sort_keys=True)
        print("")

    # get the set of cameras to deal with
    cameras = config['cameras'].values()
    if options.names:
        cams = options.names.split(',')
        camNames = config['cameras'].keys()
        cameras = []
        for cam in cams:
            if cam in camNames:
                cameras.append(config['cameras'][cam])
            else:
                fatalError("Non-existant camera '{0}'".format(cam))
    if options.verbose > 1:
        print("Camera Ids: {0}".format(cameras))

    # validate config values
    if config['numFrames'] < 0:
        fatalError("Number of frames to capture must be non-negative")
    if config['maxFrames'] < 0:
        fatalError("Number of frames to retain must be non-negative")
    if config['delay'] < 0:
        fatalError("Inter-frame delay must be non-negative")
    if not config['outPath']:
        fatalError("Must provide output path")

    # instantiate the interface object and all of the chosen camera objects
    tries = 3
    while tries > 0:
        try:
            nest = NestCam(config['user'], config['passwd'], cameras)
            break
        except Exception as e:
            if options.verbose > 0:
                sys.stderr.write("Warning: Failed to initialize nestcam: {0}".
                                 format(e))
        tries -= 1
    if tries <= 0:
        fatalError("Unable to initalize nestcam")
    cams = nest.cameras()

    if not os.path.exists(config['outPath']):
        os.makedirs(config['outPath'])
    for cam in cams:
        camName = cam.name()
        path = os.path.join(config['outPath'], camName)
        if not os.path.exists(path):
            os.makedirs(path)

    if config['testing']:
        # run tests and bail
        camNames = nest.cameraNames()
        print("CameraNames: {0}".format(camNames))

        camIds = nest.cameraIds()
        print("CameraIds: {0}".format(camIds))

        camsMap = nest.camerasMap()
        print("CamerasMap: {0}".format(camsMap))

        for cam in cams:
            '''
            print("Camera: {0} - {1}".format(cam.name(), cam.id()))
            cam.dump()
            '''
            '''
            capas = cam.capabilities()
            print("Camera: {0}, capabilities={1}".format(cam.name(), capas))
            '''
            '''
            for capa in capas:
                val = cam.getCapability(capa)
                print("Capability: {0}={1}".format(capa, val))
            '''
            events = cam.getEvents(0)
            print("Events:")
            json.dumps(events, sys.stdout, indent=4, sort_keys=True)
        return

    # capture a frame from each camera in the list, writing the images to
    #  files in the given directory, wait the given amount of time, and repeat
    count = 0
    while True:
        for cam in cams:
            if options.verbose > 1:
                print("Capturing from {0}".format(cam.name()))
            ts = datetime.utcnow().isoformat()
            try:
                img = cam.grabFrame()
            except Exception:
                continue

            # delete oldest frame if there are more than the max number of them
            camOutPath = os.path.join(config['outPath'], cam.name())
            camOutGlob = os.path.join(camOutPath, "*.jpg")
            files = glob.glob(camOutGlob)
            if len(files) > config['maxFrames']:
                files.sort()
                try:
                    if options.verbose > 1:
                        print("Removing file '{0}'".format(files[0]))
                    os.remove(files[0])
                except Exception:
                    print("FIXME")

            fPath = os.path.join(camOutPath, ts + ".jpg")
            with open(fPath, "w+") as f:
                if options.verbose > 1:
                    print("Writing frame to file '{0}'".format(fPath))
                f.write(img)
        if config['numFrames'] > 0:
            count += 1
            if count >= config['numFrames']:
                if options.verbose > 2:
                    print("Completed capture of {0} frames per camera".
                          format(count))
                break
        time.sleep(config['delay'])

if __name__ == '__main__':
    main()
