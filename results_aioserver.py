import random
import sys
import asyncio
import re
import os
import io
import requests as req
import aiohttp
from aiohttp import web
import aiohttp_cors
import numpy
from bs4 import BeautifulSoup as bs
import pytesseract
from PIL import Image as pimg
from wand.image import Image as wimg

currentdir = os.path.join(os.getcwd()) + '/'

host = 'https://results.vtu.ac.in/'
# host='https://210.212.207.149:443/'
resultpage_url = '_CBCS/resultpage.php'
indexpage_url = '_CBCS/index.php'
req.packages.urllib3.disable_warnings()
sem_regx = re.compile('Semester')
exam_name_regx = re.compile('<b>.*>(.*?) EXAMINATION RESULTS')  ##improve
catch_alert_regx = re.compile(r'alert\((.*)\)')


def handle_exception(e, risk='notify'):
    if risk == 'notify':
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        print(fname, exc_tb.tb_lineno, exc_type, e)
    pass


async def read_captcha(pic):
    pic.modulate(120)
    pic.modulate(150)
    pic.modulate(130)
    # pic.save(filename='pic.png')
    img_buffer = numpy.asarray(bytearray(pic.make_blob(format='png')), dtype='uint8')
    bytesio = io.BytesIO(img_buffer)
    pil_img = pimg.open(bytesio)
    return re.sub('[\W_]+', '', pytesseract.image_to_string(pil_img))


async def get_page(session, url, get_blob=False):
    await asyncio.sleep(0.2)
    async with session.get(url) as resp:
        # print(resp.status)
        resp.raise_for_status()
        return await resp.read() if get_blob else await resp.text()


async def post_page(session, url, data):
    await asyncio.sleep(0.2)
    async with session.post(url, data=data) as resp:
        resp.raise_for_status()
        return await resp.text()


async def get_resultpage(usn):
    global ccount
    retry_count = 0
    # cookie = {'PHPSESSID': 'q6k5bedrobcjob6opttgg11i14'+str(ccount)}
    while True:
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ttl_dns_cache=500, ssl=False)) as session:
                index_page, img_src, token, captcha_blob, captcha_code = "", "", "", "", ""
                try:
                    index_page = await get_page(session, host + indexpage_url)
                except Exception as e:
                    handle_exception(e)
                    await asyncio.sleep(random.uniform(0, 3))
                    continue
                if len(index_page) < 5000:
                    retry_count += 1
                    if retry_count > 4:
                        return None  # return meaning full error codes or throw exception
                    continue
                try:
                    img_src, token = parse_indexpage(index_page)
                    captcha_blob = await get_page(session, host + img_src, True)
                except Exception as e:
                    handle_exception(e)
                    await asyncio.sleep(random.uniform(0, 3))
                    continue
                if len(captcha_blob) < 1000:
                    continue
                pic = wimg(blob=captcha_blob)
                try:
                    captcha_code = await read_captcha(pic)  ##cpu blocking
                except Exception as e:
                    handle_exception(e)
                    await asyncio.sleep(random.uniform(0, 3))
                    continue
                # print(captcha_code)
                if len(captcha_code) != 6:
                    continue
                data = {'Token': token, 'lns': usn, 'captchacode': captcha_code}
                resultpage = ""
                try:
                    resultpage = await post_page(session, host + resultpage_url, data)
                except Exception as e:
                    handle_exception(e)
                    await asyncio.sleep(random.uniform(3, 6))
                    continue
                # if len(resultpage) < 1000:  #optimise alert decetion
                try:
                    alert = catch_alert_regx.findall(resultpage)[0]
                    if 'captch' in alert:
                        continue
                    elif 'not available' in alert:
                        print(usn, alert)
                        return "invalid"
                    elif 'check' in alert or 'after' in alert or 'again' in alert:
                        # print(usn, alert)
                        await asyncio.sleep(random.uniform(0, 3))
                        continue
                    # print(usn, alert)
                    # return meaning full err data
                except Exception as e:
                    handle_exception(e, 'expected')
                    pass
                return resultpage
        except Exception as e:
            handle_exception(e)
            pass


def parse_indexpage(page):
    soup = bs(page, 'html.parser')
    img_src = soup.find(alt="CAPTCHA code")['src']
    token = soup.find('input')['value']
    return img_src, token


def parse_resultpage(page):
    soup = bs(page, 'html.parser')
    # print(soup.find_all('div',{'class':'divTableCell'}))
    name = soup.find('table').find_all('tr')[1].find_all('td')[1].text[2:]
    sems = [list(i for i in e.split() if i.isdigit())[0] for e in
            soup(text=sem_regx)]  # sems=[ e[11] for e in soup(text=sem_regx)]
    result = soup.find_all('div', {'class': 'divTableBody'})
    return name, sems, result


def get_dept(usn):
    return re.findall(r'[0-9]([a-z]{2}|[a-z]{3}])[0-9]*?', usn)[1]


def get_batch(usn):
    return re.findall(r'[a-z]([0-9][0-9])[a-z]', usn)[0]


def get_scheme(subcode):
    return subcode[0:2]


def generate_output(usn, name, sems, result):
    for j in range(0, len(sems)):
        sem = sems[j]
        dept = get_dept(usn)
        batch = '20' + get_batch(usn)
        rows = result[j].find_all('div', {'class': 'divTableRow'})[1:]
        scheme = '20' + get_scheme(rows[0].text.strip().replace(',', '').split('\n')[0])
        #file = 'Data-' + dept.upper() + '-' + batch + '-' + scheme + '-' + sem + ('-arrear' if j != 0 else '') + '.csv'
        li = []
        li.append([usn, name, sem])
        # temp.append([usn,name,sems[j]])
        for row in rows:
            li.extend(row.text.strip().replace(',', '').split('\n'))
        return str(li).replace('[','').replace(']','').replace('\'','')


async def async_executer(LOOP, usn):
    try:
        resultpage = await LOOP.create_task(get_resultpage(usn))
        if resultpage == "invalid":
            return resultpage
        try:
            name, sems, result = parse_resultpage(resultpage)
            return generate_output(usn, name, sems, result)
        except Exception as e:
            handle_exception(e)
            return 'error while processing:' + usn
    except Exception as e:
        handle_exception(e)
        return 'error while processing:' + usn

def generate_list(lwr,upr):
    li=[]
    if int(lwr[7:].lstrip('0'))>int(upr[7:].lstrip('0')):
        lwr,upr=upr,lwr
    for i in range(int(lwr[7:].lstrip('0')),int(upr[7:].lstrip('0'))+1):
        li.append(lwr[0:6]+str(i).zfill(3))
    return li

# Setting up endpoints
routes = web.RouteTableDef()

@routes.get("/list")
async def send_list(request):
    try:
        range= request.rel_url.query.get('range').split('-')
        return web.json_response(generate_list(range[0],range[1]))
    except:
        return web.json_response(['1cr17cs154'])

@routes.get("/result/{usn}")
async def send_res(request):
    try:
        usn = request.match_info['usn'].lower()
        return web.json_response({'data':await async_executer(my_loop,usn)})
    except Exception as e:
        return web.json_response({'data':'ops...error-detail:'+str(e)})

my_loop = asyncio.get_event_loop()
app = web.Application()

# Configure default CORS settings.
cors = aiohttp_cors.setup(app, defaults={
    "*": aiohttp_cors.ResourceOptions(
        allow_credentials=True,
        expose_headers="*",
        allow_headers="*",
    )
})
app.add_routes(routes)
# Configure CORS on all routes.
for route in list(app.router.routes()):
    cors.add(route)

runner = aiohttp.web.AppRunner(app)
my_loop.run_until_complete(runner.setup())
site = aiohttp.web.TCPSite(runner, '0.0.0.0', 8000)
my_loop.run_until_complete(site.start())

my_loop.run_forever()

