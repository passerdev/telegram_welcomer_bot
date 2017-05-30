# -*- coding: utf-8 -*-

import asyncio
import logging
import sqlite3
from datetime import datetime
from itertools import chain
from json import dumps
from random import choice
import time

import telepot
import telepot.aio

import config


logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=logging.INFO)
logger = logging.getLogger(config.bot_username)
bot = telepot.aio.Bot(config.bot_token)
loop = asyncio.get_event_loop()

user_ans_db = sqlite3.connect("answers.db")
user_ans_curr = user_ans_db.cursor()

admins_list = config.load_admins()
got_user_response = list(chain.from_iterable(user_ans_curr.execute("SELECT id FROM user_answers")))
messages_from_users = list(chain.from_iterable(user_ans_curr.execute("SELECT user_message FROM user_answers")))
new_users, left_users = {}, {}
curr_users, time_users = {}, {}
prev_bot_messages = {}
chat_semaphores = {}


def username_from_msg(msg, flag=0):
    if flag == 0:
        if 'username' in msg['from']:
            return f"@{msg['from']['username']}"
        elif 'last_name' in msg['from']:
            return f"{msg['from']['first_name']} {msg['from']['last_name']}"
        else:
            return f"{msg['from']['first_name']}"
    elif flag == 1:
        if 'username' in msg['new_chat_member']:
            return f"@{msg['new_chat_member']['username']}"
        elif 'last_name' in msg['new_chat_member']:
            return f"{msg['new_chat_member']['first_name']} {msg['new_chat_member']['last_name']}"
        else:
            return f"{msg['new_chat_member']['first_name']}"
    elif flag == 2:
        if 'username' in msg['forward_from']:
            return f"@{msg['forward_from']['username']}"
        elif 'last_name' in msg['forward_from']:
            return f"{msg['forward_from']['first_name']} {msg['forward_from']['last_name']}"
        else:
            return f"{msg['forward_from']['first_name']}"
    elif flag == 3:
        if 'username' in msg['left_chat_member']:
            return f"@{msg['left_chat_member']['username']}"
        elif 'last_name' in msg['left_chat_member']:
            return f"{msg['left_chat_member']['first_name']} {msg['left_chat_member']['last_name']}"
        else:
            return f"{msg['left_chat_member']['first_name']}"


def switch_welcome_message():
    current_hour = datetime.now().hour
    if current_hour in config.night_time:
        return choice(config.daytime_messages['night'])
    elif current_hour in config.morning_time:
        return choice(config.daytime_messages['morning'])
    elif current_hour in config.day_time:
        return choice(config.daytime_messages['day'])
    elif current_hour in config.evening_time:
        return choice(config.daytime_messages['evening'])


async def welcome_user(msg_id, chat_id):
    global chat_semaphores, new_users, left_users, curr_users, time_users, prev_bot_messages
    times = []
    update = False
    while not new_users[chat_id].empty() or not left_users[chat_id].empty():
        logger.debug("Starting to extract users")
        curr_time = time.time()
        times.append(curr_time)
        while not new_users[chat_id].empty():
            user = await new_users[chat_id].get()
            curr_users[chat_id].append(user)
            time_users[chat_id][user] = curr_time
        while not left_users[chat_id].empty():
            user = await left_users[chat_id].get()
            if user in curr_users[chat_id]: curr_users[chat_id].remove(user)
        for user in curr_users[chat_id]:
            if time_users[chat_id][user] + config.wait_response_time <= curr_time: await left_users[chat_id].put(user)
            elif time_users[chat_id][user] not in times: update = True
        logger.debug("Waiting for new users to come in")
        await asyncio.sleep(config.wait_time)

    if update: await bot.deleteMessage(telepot.message_identifier(prev_bot_messages[chat_id]))
    
    logger.debug("Welcoming user(s)")
    if len(curr_users[chat_id]) == 1:
        prev_bot_messages[chat_id] = await bot.sendMessage(chat_id=chat_id,
                              text=' '.join([f"{switch_welcome_message()} {curr_users[chat_id][0]}!", choice(config.welcome_user)]),
                              reply_to_message_id=msg_id)
    elif len(curr_users[chat_id]) > 1:
        prev_bot_messages[chat_id] = await bot.sendMessage(chat_id=chat_id,
                              text=' '.join([f"{switch_welcome_message()} {', '.join(curr_users[chat_id]).strip()}!", choice(config.welcome_users)]))
    chat_semaphores[chat_id] = False


async def handle(msg):
    global chat_semaphores, new_users, left_users, curr_users, time_users
    content_type, chat_type, chat_id = telepot.glance(msg)
    if chat_id not in new_users: new_users[chat_id] = asyncio.Queue()
    if chat_id not in left_users: left_users[chat_id] = asyncio.Queue()
    if chat_id not in curr_users: curr_users[chat_id] = []
    if chat_id not in time_users: time_users[chat_id] = {}
    if chat_id not in chat_semaphores:
        chat_semaphores[chat_id] = False
    if chat_type == 'supergroup' and msg['from']['id'] in admins_list:
        if 'text' in msg:
            if msg['text'] == "/get_id":
                if 'reply_to_message' in msg:
                    await bot.sendMessage(chat_id=chat_id,
                                          text=f"User ID: {msg['reply_to_message']['from']['id']}",
                                          reply_to_message_id=msg['message_id'])
            if msg['text'] == "/rules":
                await bot.sendMessage(chat_id=chat_id,
                                      text=config.rules)
    if 'new_chat_member' in msg and chat_type == 'supergroup':
        logger.info(f"Got new chat member {msg['new_chat_member']['first_name']}")
        await new_users[chat_id].put(username_from_msg(msg, flag=1))
        if not chat_semaphores[chat_id]:
            loop.create_task(welcome_user(msg['message_id'], chat_id))
            chat_semaphores[chat_id] = True
            logger.debug("Started coroutine")
    if 'left_chat_member' in msg and chat_type == 'supergroup':
        logger.info(f"Got left chat member {msg['left_chat_member']['first_name']}")
        await left_users[chat_id].put(username_from_msg(msg, flag=3))
    if 'reply_to_message' in msg:
        if msg['reply_to_message']['from']['username'] == config.bot_username[1:]:
            if msg['from']['id'] not in got_user_response:
                logger.info(f"Got response from user: {msg['from']['first_name']}, User ID: {msg['from']['id']}")
                user = username_from_msg(msg)
                user_ans_curr.execute("INSERT INTO user_answers (id, message_id, username, user_message) VALUES (?, ?, ?, ?)",
                                      (msg['from']['id'], msg['message_id'], user, msg['text']))
                user_ans_db.commit()
                got_user_response.append(msg['from']['id'])
                if user in curr_users[chat_id]: left_users[chat_id].put(user)
    elif chat_id in admins_list:
        if 'forward_from' in msg:
            if msg['text'] not in messages_from_users:
                user = username_from_msg(msg, flag=2)
                user_ans_curr.execute("INSERT INTO user_answers (id, message_id, username, user_message) VALUES (?, ?, ?, ?)",
                                      (msg['forward_from']['id'], 0, user, msg['text']))
                user_ans_db.commit()
                await bot.sendMessage(chat_id=chat_id,
                                      text="Ответ был успешно записан в базу данных")
                messages_from_users.append(msg['text'])
                if user in curr_users[chat_id]: left_users[chat_id].put(user)
            else:
                await bot.sendMessage(chat_id=chat_id,
                                      text="Ответ уже есть в базе данных")
    logger.info(f"Chat: {content_type} {chat_type} {chat_id}\n"
                f"{dumps(msg, indent=4, ensure_ascii=False)}")


def main():
    loop.create_task(bot.message_loop(handle))

    loop.run_forever()


if __name__ == "__main__":
    main()
