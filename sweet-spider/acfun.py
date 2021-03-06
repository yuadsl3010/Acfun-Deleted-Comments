#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# Created on 2015-07-29 15:11:25
# Project: Acfun

import re
import json
import datetime

import pymysql.cursors

from pyspider.libs.base_handler import *

class Handler(BaseHandler):
    crawl_config = {
        'headers': {
            'Host': 'www.acfun.tv',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.125 Safari/537.36'
        }
    }

    api_get_comment = 'http://www.acfun.tv/comment_list_json.aspx?contentId='
    api_get_info = ''

    #每隔三分钟刷新一次
    @every(minutes=3)
    def on_start(self):
        """
        入口函数
        """
        self.crawl('http://www.acfun.tv/v/list110/index.htm', callback=self.index_page, force_update=True)
        self.crawl('http://www.acfun.tv/v/list73/index.htm', callback=self.index_page, force_update=True)
        self.crawl('http://www.acfun.tv/v/list74/index.htm', callback=self.index_page, force_update=True)
        self.crawl('http://www.acfun.tv/v/list75/index.htm', callback=self.index_page, force_update=True)


    def index_page(self, response):
        """
        解析主页
        """
        for each in response.doc('a[href^="http"]').items():
            #reg_result = re.match(r"http://www.acfun.tv/[av]/a[bc](\d+)", each.attr.href)
            #目前只抓取文章和视频
            reg_result = re.match(r"http://www.acfun.tv/a/ac(\d+)", each.attr.href)
            if reg_result:
                self.crawl(each.attr.href, callback=self.parse_page, age=60,
                           save={'contentId':reg_result.group(1)})

    def parse_page(self, response):
        """
        解析内页
        爬第1页评论
        """
        ac_id = response.save['contentId']
        ac_type = response.doc('#area-title-view>div.l>p>a').eq(1).text()
        ac_title = response.doc('#txt-title-view').text()
        ac_up = response.doc('#area-title-view>div.l>p>a').eq(2).text()
        ac_post_time = response.doc('#area-title-view>div.l>p>span').eq(0).text()
        ac_url = response.url

        #没问题
        accommentsinfo = Accommentsinfo(ac_id, ac_type, ac_title, ac_up, ac_post_time, ac_url)
        #存一下
        accommentsinfo.save()

        url = 'http://www.acfun.tv/comment_list_json.aspx?contentId='+ac_id+'&currentPage=1'
        self.crawl(url, callback=self.parse_first_comment, age=60, priority=2,
                   save={'info':accommentsinfo.get_info()})

    def parse_first_comment(self, response):
        """
        解析评论第一页
        分发其他页评论
        """
        info = response.save['info']

        json_data = json.loads(response.text)
        total_page = json_data['totalPage']
        comments = json_data['commentContentArr']

        #首先分发其他页评论
        for page in range(2, total_page+1):
            url = 'http://www.acfun.tv/comment_list_json.aspx?contentId=' + \
                  str(info['id']) + '&currentPage=' + str(page)
            self.crawl(url, callback=self.parge_comment, age=30*60,
                       save={'info':info})

        #然后解析第一页评论
        return self.analyze_comment(info, comments)


    def parge_comment(self, response):
        """
        解析评论页面
        """
        info = response.save['info']

        """
        检查是否删除
        否-->更新数据库
        是-->检查数据库
        """
        json_data = json.loads(response.text)
        comments = json_data['commentContentArr']

        return self.analyze_comment(info, comments)


    def analyze_comment(self, info, comments):
        """
        分析评论
        """
        for _, comment in comments.items():
            new_comment = Accomments(comment['cid'], info['id'])

            ac_user_id = comment['userID']
            if ac_user_id != 4:
                new_comment.set_content(comment['content'])
                new_comment.set_user_name(comment['userName'])
                new_comment.set_layer(comment['count'])
                self.check_siji(new_comment)
                new_comment.save()
            else:
                return self.update_delete(comment['cid'], info['url'])

    def update_delete(self, cid, url):
        """
        更新delete
        """
        connection = pymysql.connect(host='localhost',
                                     user='deleteso',
                                     passwd='deletepassso',
                                     db='deleteso',
                                     charset='utf8',
                                     cursorclass=pymysql.cursors.DictCursor)
        try:
            with connection.cursor() as cursor:
                # Read a single record
                sql = "SELECT * FROM `accomments` WHERE `cid`=%s AND isDelete != 1 "
                cursor.execute(sql, (cid))
                result = cursor.fetchone()
                if result != None:
                    sql = "UPDATE `accomments` SET isDelete=1, checkTime=%s WHERE cid=%s"
                    cursor.execute(sql, (str(datetime.datetime.now()), cid))
                    connection.commit()

        finally:
            connection.close()

        if result != None:
            result['checkTime'] = result['checkTime'].strftime("%Y-%m-%d %H:%M:%S")
            result['url'] = url
            result.pop('isDelete', None)
            return result

    def check_siji(self, comment):
        """
        检查是否老司机
        """
        if comment.get_content().find(u"佛曰：") > -1 \
        or comment.get_content().find(u"如是我闻：") > -1 \
        or comment.get_content().find(u"*：") > -1:
            comment.set_siji(1)
        elif comment.get_content().find(u"ed2k://") > -1:
            #linkUrl = "ed2k:" + comment.get_content()[comment.get_content().find(u"ed2k://"):]
            #encodedContent = comment.get_content().replace(self.encodeFoyu(linkUrl),linkUrl,1)
            #comment.set_content(encodedContent)
            comment.set_siji(1)
        elif comment.get_content().find(u"magnet:?") > -1:
            #linkUrl = "magnet:?" + comment.get_content()[comment.get_content().find(u"magnet:?"):]
            #encodedContent = comment.get_content().replace(self.encodeFoyu(linkUrl),linkUrl,1)
            #comment.set_content(encodedContent)
            comment.set_siji(1)
        else:
            comment.set_siji(0)

class Accommentsinfo(object):
    """
    文章/视频/番剧信息
    """
    info = {}

    def __init__(self, ac_id, ac_type, ac_title, ac_up, ac_post_time, ac_url):
        self.info['id'] = int(ac_id)
        self.info['type'] = ac_type
        self.info['title'] = ac_title
        self.info['up'] = ac_up
        self.info['postTime'] = ac_post_time
        self.info['url'] = ac_url

    def get_info(self):
        return self.info

    def set_id(self, ac_id):
        self.info['id'] = int(ac_id)

    def set_type(self, ac_type):
        self.info['type'] = ac_type

    def set_title(self, ac_title):
        self.info['title'] = ac_title

    def set_up(self, ac_up):
        self.info['up'] = ac_up

    def set_postTime(self, ac_post_time):
        self.info['postTime'] = ac_post_time

    def set_url(self, ac_url):
        self.info['url'] = ac_url

    def save(self):
        connection = pymysql.connect(host='localhost',
                                     user='deleteso',
                                     passwd='deletepassso',
                                     db='deleteso',
                                     charset='utf8',
                                     cursorclass=pymysql.cursors.DictCursor)
        try:
            with connection.cursor() as cursor:
                # Create a new record
                sql = "INSERT INTO `accommentsinfo`(`id`, `type`, `title`, `up`, `postTime`, `url`) VALUES (%s, %s, %s, %s, %s, %s) \
                       ON DUPLICATE KEY UPDATE type=type, title=title, up=up, postTime=postTime, url=url"
                cursor.execute(sql, (self.info['id'], self.info['type'], self.info['title'], self.info['up'], self.info['postTime'], self.info['url']))

            # connection is not autocommit by default. So you must commit to save
            # your changes.
            connection.commit()

        finally:
            connection.close()

class Accomments(object):
    """
    评论信息
    """

    info = {}

    def __init__(self, ac_cid, ac_acid):
        self.info['cid'] = int(ac_cid)
        self.info['acid'] = int(ac_acid)
        self.info['checkTime'] = str(datetime.datetime.now())
        self.info['isDelete'] = 0

    def get_info(self):
        return self.info

    def get_content(self):
        return self.info['content']

    def set_content(self, ac_content):
        self.info['content'] = ac_content

    def set_user_name(self, ac_user_name):
        self.info['userName'] = ac_user_name

    def set_layer(self, ac_layer):
        self.info['layer'] = int(ac_layer)

    def set_siji(self, ac_siji):
        self.info['siji'] = int(ac_siji)

    def save(self):
        connection = pymysql.connect(host='localhost',
                                     user='deleteso',
                                     passwd='deletepassso',
                                     db='deleteso',
                                     charset='utf8',
                                     cursorclass=pymysql.cursors.DictCursor)
        try:
            with connection.cursor() as cursor:
                # Create a new record
                sql = "INSERT INTO `accomments`(`cid`, `content`, `userName`, `layer`, `acid`, `isDelete`, `siji`, `checkTime`) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) \
                       ON DUPLICATE KEY UPDATE content=content, userName=userName, layer=layer, acid=acid, isDelete=isDelete, siji=siji, checkTime=VALUES(checkTime) "
                cursor.execute(sql, (self.info['cid'], self.info['content'], self.info['userName'], self.info['layer'], self.info['acid'], self.info['isDelete'], self.info['siji'], self.info['checkTime']))

            # connection is not autocommit by default. So you must commit to save
            # your changes.
            connection.commit()

        finally:
            connection.close()
