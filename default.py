import sys, xbmcgui, xbmcplugin, xbmcaddon
import os, requests, urllib, urllib2, cookielib, re, json, datetime, time
from urlparse import parse_qsl
from bs4 import BeautifulSoup 


addon           = xbmcaddon.Addon(id='plugin.video.ufcfightpass')
addon_url       = sys.argv[0]
addon_handle    = int(sys.argv[1])
addon_BASE_PATH = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
COOKIE_FILE     = os.path.join(addon_BASE_PATH, 'cookies.lwp')
CACHE_FILE      = os.path.join(addon_BASE_PATH, 'data.json')
c_base_url      = 'https://www.ufc.tv/category/'
ua              = 'Mozilla/5.0 (Linux; Android 6.0.1; D6603 Build/23.5.A.0.570; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/56.0.2924.87 Mobile Safari/537.36 android mobile ufc 7.0310'


def get_creds():
    if len(addon.getSetting('email')) == 0 or len(addon.getSetting('password')) == 0:
        return None
    return {
        'username': addon.getSetting('email'),
        'password': addon.getSetting('password')
    }


def post_auth(creds):
    url = 'https://www.ufc.tv/page/fightpass' 
    #ua = 'Mozilla/5.0 (iPad; CPU OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Mobile/12F69'

    #TODO: create a common func to load a session with cookies already set
    #TODO: don't attempt to login unless we need to??
    cj = cookielib.LWPCookieJar(COOKIE_FILE)
    try:
        cj.load()
    except:
        pass

    # build an opener that we can reuse here
    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj))
    opener.addheaders = [('User-Agent', urllib.quote(ua))]

    # pre-auth, load in the required cookies to be used in the next step
    try:
        resp = opener.open(url)
    except urllib2.URLError, e:
        print e.args
        return None

    s_url = 'https://www.ufc.tv/secure/signin?parent=' + url
    try:
        s_resp = opener.open(s_url)
    except urllib2.URLError, e:
        print e.args
        return None
    
    # login with creds and capture the auth response
    a_url = 'https://www.ufc.tv/secure/authenticate'
    try:
        auth_resp = opener.open(a_url, urllib.urlencode(creds))
    except urllib2.URLError, e:
        print e.args
        return None

    rdata = auth_resp.read()
    auth_resp.close()

    cj.save(COOKIE_FILE, ignore_discard=True)

    if auth_resp.code == 200:
        #TODO: need to handle login locked scenario as well
        soup = BeautifulSoup(rdata,"html.parser")
        code = soup.find('code').get_text()
        if code == 'loginsuccess':
            return True
        else:
            print('Authentication error. Status: ' + code)

    return False


def publish_point(video):
    # Fetch the stream url for the video
    # TODO: if this fails, it may also be cause the cookie has expired / logged in on another device (status 400)
    #  * in this case, we may need to re-auth, so we can play the video
    url = 'https://www.ufc.tv/service/publishpoint'
    headers = {
        'User-Agent': ua
    }

    payload = {
        'id': video['id'],
        'type': 'video',
        'nt': '1',
        'format': 'json'
    }

    cj = cookielib.LWPCookieJar(COOKIE_FILE)
    try:
        cj.load(COOKIE_FILE, ignore_discard=True)
    except:
        pass

    s = requests.Session()
    s.cookies = cj
    resp = s.post(url, data=payload, headers=headers, verify=False)
    # normally status 400 if have an expired session
    status = resp.status_code
    result = resp.json()
    if not result:
        return status, None

    path = result['path'].replace('android', 'ced')
    return status, path


def get_categories():
    # Fetch the main UFC Fight Pass cat-a-ma-gories
    url = c_base_url + 'fightpass?format=json'
    cj = cookielib.LWPCookieJar(COOKIE_FILE)
    try:
        cj.load(COOKIE_FILE, ignore_discard=False)
    except:
        pass

    headers = {
        'User-Agent': ua
    }

    s = requests.Session()
    s.cookies = cj
    resp = s.get(url, headers=headers, verify=True)
    data = resp.json()

    results = []

    for c in data['subCategories']:
        results.append({
            'title': c['name'],
            'url': c_base_url +  c['seoName']
        })

    return results


def main():
    creds = get_creds()
    if creds is None:
        # TODO: ensure we have credentials stored first, and if not, prompt for them.
        dialog = xbmcgui.Dialog()
        result = dialog.yesno('UFC Fight Pass', 'You have not yet signed in to UFC Fight Pass.\nWould you like to sign in now?')
        if result:
            addon.openSettings()
            creds = get_creds()
        else:
            # build free option menu
            dialog = xbmcgui.Dialog()
            dialog.ok('UFC Fight Pass', 'You have not yet signed in to UFC Fight Pass. \nPlease enjoy some free videos until you do.')
            create_free_menu()

    if creds:
        if not post_auth(creds):
            dialog = xbmcgui.Dialog()
            dialog.ok('Authorization Error', 'Authorization to UFC Fight Pass failed. \nPlease enjoy some free videos.')
            # build free option (provided by ufc.tv) menu for those that do not have Fight Pass.
            create_free_menu()
        else:
            # fetch the main categories to start, and display the main menu
            # TODO: add featured categories like: Trending on Fight Pass, Recent Events etc
            categories = get_categories()
            build_menu(categories,True)


def create_free_menu():
    # TODO: this should load / save to cache as well? Refactor needed.
    data = get_data('http://www.ufc.tv/category/free-video')
    vids = get_parsed_vids(data)
    build_menu(vids,False)


def build_menu(items,toplevel):
    listing = []
    first = items[0]
    is_folder = 'id' not in first.keys()

    for i in items:
        thumb = i['thumb'] if not is_folder else None
        # stupid encoding hack for now..
        try:
            i_title = i['title'].encode('utf-8')
        except:
            i_title = i['title']

        title = '[B][{0}][/B]  {1}'.format(i['airdate'], i_title) if not is_folder else i_title
        item = xbmcgui.ListItem(label=title, thumbnailImage=thumb) 

        if is_folder:
            url = '{0}?action=traverse&u={1}&t={2}'.format(addon_url, i['url'], i_title)
        else:
            url = '{0}?action=play&i={1}&t={2}'.format(addon_url, i['id'], i_title)

        listing.append((url, item, is_folder))
    if (toplevel == True):
        url = '{0}?action=search&u={1}&t={2}'.format(addon_url,'UFC 27' , 'Search: UFC 27')
        listing.append((url,xbmcgui.ListItem(label='Search',thumbnailImage=None),True))

    if len(listing) > 0:
        xbmcplugin.addDirectoryItems(addon_handle, listing, len(listing))
        # force thumbnail view mode??
        #xbmc.executebuiltin('Container.SetViewMode(500)')
        xbmcplugin.endOfDirectory(addon_handle)


def get_data(url):
    if 'json' not in url:
        url = url + '?format=json'
    print('get_data() url: ' + url)
    headers = {
        'User-Agent': ua
    }

    cj = cookielib.LWPCookieJar(COOKIE_FILE)
    try:
        cj.load(COOKIE_FILE, ignore_discard=True)
    except:
        pass

    s = requests.Session()
    s.cookies = cj
    resp = s.get(url, headers=headers, verify=False)
    if not resp.status_code == 200:
        return None

    return resp.json()


def get_parsed_subs(data):
    #print('UFCFP: get_parsed_subs:')
    #print(data)
    # if we're at video depth, signal as such
    if 'programs' in data.keys():
        return []

    subCategories = []
    for sc in data['subCategories']:
        subCategories.append({
            'title': sc['name'], 
            'url': c_base_url + sc['seoName']
        })

    return subCategories

    
def get_parsed_vids(data):
    #print('UFCFP: get_parsed_vids:')
    #print(data)
    img_base_url = 'https://neulionmdnyc-a.akamaihd.net/u/ufc/thumbs/'
    v_list = []
    for v in data['programs']:
        v_list.append({
            'id': v['id'], 
            'title': v['name'], 
            'thumb': img_base_url + v['image'], 
            'airdate': datetime.datetime.strftime(parse_date(v['releaseDate'], '%Y-%m-%dT%H:%M:%S.%f'), '%Y-%m-%d'), 
            'plot': v['description']
        })
            
    return v_list

def parse_date(dateString, format='%Y-%m-%d %H:%M:%S.%f'):
    try:
        p_date = datetime.datetime.strptime(dateString, format)
    except TypeError:
        p_date = datetime.datetime.fromtimestamp(time.mktime(time.strptime(dateString, format)))
    return p_date


def needs_refresh(cache_date):
    p_date = parse_date(cache_date)
    delta = (datetime.datetime.now() - p_date).seconds / 60
    interval = addon.getSetting('cacheInterval')
    print 'UFCFP: Minutes elapsed since last cached: {0}. Set at: {1}.'.format(delta, interval)
    return delta >= int(interval)


def traverse(url):
    print("UFCFP: Traversing categories for URL: " + url)
    # check / load from cache if available and prior to next refresh interval
    items  = None
    cached = get_cacheItem(url)
    if cached and not needs_refresh(cached['lastCached']):
        items = cached['data']
        print('UFCFP: Using cached data..')

    else:
        print('UFCFP: No cached data. Fetching new data..')
        data = get_data(url)
        if not data:
            # ideally, we need to throw an error here, because we received no data from the server
            print('UFCFP get_data() returned no data')
            dialog = xbmcgui.Dialog()
            dialog.ok('Error', 'Unable to load content. Check log for more details.')

        if data['paging']:
            if data['paging']['count'] == 0: # if we did a search we might get empty results
                dialog = xbmcgui.Dialog()
                dialog.ok('Error', 'No results found')
                return []

        items = get_parsed_subs(data)
        save_cacheItem(url, {
            'data': items, 
            'lastCached': str(datetime.datetime.now())
        })

        if len(items) == 0:
            # no sub categories, so we're likely at video list depth
            items = get_parsed_vids(data)
            save_cacheItem(url, {
                'data': items, 
                'lastCached': str(datetime.datetime.now())
            })
            # TODO: sort??

    build_menu(items,False)


def play_video(v_id, v_title):
    # Fetch the stream url and play the video
    status, stream = publish_point({ 'id': v_id })
    if status == 400:
        #TODO: maybe pop up a messge to the user that it looks like they logged onto another device
        # ask if they would like to end that session and play on current device instead?
        # at this point, we likely need to re-auth
        if post_auth(get_creds()):
            status, stream = publish_point({ 'id': v_id })
        else:
            dialog = xbmcgui.Dialog()
            dialog.ok('Authorization Error', 'Authorization to UFC Fight Pass failed.')

    if stream:
        item = xbmcgui.ListItem(label=v_title)
        xbmc.Player().play(stream, item)
    else:
        dialog = xbmcgui.Dialog()
        dialog.ok('Playback Error', 'Unable to play video: ' + v_title)

    

def router(paramstring):
    params = dict(parse_qsl(paramstring))
    if params:
        action = params['action']
        if action == 'listing':
            main()
        elif action == 'play':
            play_video(params['i'], params['t'])
        elif action == 'traverse':
            traverse(params['u'])
        elif action == 'search':
            keyboard = xbmc.Keyboard()
            keyboard.doModal()
            if keyboard.isConfirmed() and keyboard.getText():
                query = keyboard.getText()
                traverse('https://www.ufc.tv/search?param={}&format=json'.format(query))
    else:
        main()



# data caching layer -- should move this into another class..
# should be consumed inside some sort of data repo class, and bits above abstracted out into that as well..
def get_allCache():
    try:
        fs = open(CACHE_FILE, 'r')
        data = json.load(fs)
        fs.close()
        return data
    except:
        return {}


def get_cacheItem(key):
    try:
        fs = open(CACHE_FILE, 'r')
        data = json.load(fs)
        fs.close()
        return data[key]
    except:
        return None


def save_cacheItem(key, data):
    try:
        # get cache / set value on key, save back to cache file
        cache = get_allCache()
        cache[key] = data
        fs = open(CACHE_FILE, 'w')
        json.dump(cache, fs)
        fs.close()
    except: 
        return False
    return True


if __name__ == '__main__':
    router(sys.argv[2][1:])
