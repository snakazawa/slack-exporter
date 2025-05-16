#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slack Export Tool - JSONエクスポーター

指定されたSlackチャンネルから特定の時間区間のメッセージをJSONとしてエクスポートします。
スレッド返信やリアクションも含めて構造化されたデータを出力します。
"""

import argparse
import datetime
import json
import logging
import os
import re
import sys
import time
from typing import Dict, List, Optional, Any, Tuple

import pytz
import requests
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# 定数定義
DEFAULT_LIMIT = 1000  # APIで取得する投稿数やスレッド返信数の上限
MAX_RETRIES = 5  # API呼び出しの最大リトライ回数
RETRY_DELAY = 2  # リトライ間隔（秒）
RATE_LIMIT_DELAY = 60  # レート制限時の待機時間（秒）
JST = pytz.timezone('Asia/Tokyo')  # 日本時間タイムゾーン

# ロガー設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger('slack_exporter')


def validate_datetime_format(dt_str: str) -> bool:
    """時間文字列がYYYY-MM-DDTHH:mm:ss形式かチェックする"""
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$'
    return bool(re.match(pattern, dt_str))


def parse_datetime(dt_str: str) -> float:
    """YYYY-MM-DDTHH:mm:ss形式（JST）の文字列をUNIXタイムスタンプに変換"""
    if not validate_datetime_format(dt_str):
        raise ValueError(f"日時フォーマットが無効です: {dt_str}、YYYY-MM-DDTHH:mm:ss形式で入力してください")
    
    try:
        dt = datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        # タイムゾーン指定がなければJSTとみなす
        localized_dt = JST.localize(dt)
        # UNIXタイムスタンプに変換（秒単位）
        return localized_dt.timestamp()
    except ValueError as e:
        raise ValueError(f"日時の解析に失敗しました: {e}")
    except Exception as e:
        raise ValueError(f"日時の処理中にエラーが発生しました: {e}")


def call_slack_api_with_retry(client: WebClient, method: str, **kwargs) -> Dict:
    """Slack APIを呼び出し、必要に応じてリトライ処理を行う"""
    retries = 0
    while retries <= MAX_RETRIES:
        try:
            response = getattr(client, method)(**kwargs)
            return response.data
        except SlackApiError as e:
            if e.response.get('error') == 'ratelimited':
                # レート制限にかかった場合
                retry_after = int(e.response.headers.get('Retry-After', RATE_LIMIT_DELAY))
                logger.warning(f"レート制限にかかりました。{retry_after}秒後にリトライします...")
                time.sleep(retry_after)
                continue
            elif retries < MAX_RETRIES:
                # その他のエラーは一定回数リトライ
                retries += 1
                logger.warning(f"APIエラー発生: {e}、リトライ {retries}/{MAX_RETRIES}")
                time.sleep(RETRY_DELAY * retries)  # 遅延を増やしながらリトライ
            else:
                # 最大リトライ回数を超えた場合
                logger.error(f"最大リトライ回数を超えました。エラー: {e}")
                raise
        except Exception as e:
            logger.error(f"予期せぬエラーが発生しました: {e}")
            if retries < MAX_RETRIES:
                retries += 1
                logger.warning(f"リトライ {retries}/{MAX_RETRIES}")
                time.sleep(RETRY_DELAY * retries)
            else:
                raise
    raise Exception('Maximum retries exceeded for Slack API call')


def get_channel_id(client: WebClient, channel_name: str) -> str:
    """チャンネル名からチャンネルIDを取得する"""
    try:
        # パブリックチャンネルリストを取得
        response = call_slack_api_with_retry(client, "conversations_list", types="public_channel")
        channels = response.get('channels', [])
        
        # プライベートチャンネルも取得（権限があれば）
        private_response = call_slack_api_with_retry(client, "conversations_list", types="private_channel")
        channels.extend(private_response.get('channels', []))
        
        # チャンネル名が一致するものを探す
        for channel in channels:
            if channel['name'] == channel_name:
                return channel['id']
        
        raise ValueError(f"チャンネル '{channel_name}' が見つかりません。チャンネル名を確認してください。")
    except SlackApiError as e:
        logger.error(f"チャンネルIDの取得に失敗しました: {e}")
        raise


def get_conversation_history(client: WebClient, channel_id: str, 
                            start_time: float, end_time: float, 
                            limit: int = DEFAULT_LIMIT) -> List[Dict]:
    """指定された時間範囲内のチャンネル投稿履歴を取得"""
    messages = []
    cursor = None
    
    while True:
        try:
            # 会話履歴を取得
            response = call_slack_api_with_retry(
                client,
                "conversations_history",
                channel=channel_id,
                limit=limit,
                oldest=str(start_time),
                latest=str(end_time),
                cursor=cursor
            )
            
            batch = response.get('messages', [])
            if batch:  # 空のバッチをチェック
                messages.extend(batch)
            
            # ページネーション処理
            cursor = response.get('response_metadata', {}).get('next_cursor')
            if not cursor:  # カーソルがない場合は終了
                break
                
        except SlackApiError as e:
            logger.error(f"会話履歴の取得に失敗しました: {e}")
            raise
    
    return messages


def get_thread_replies(client: WebClient, channel_id: str, thread_ts: str, 
                      limit: int = DEFAULT_LIMIT) -> List[Dict]:
    """スレッドの返信を取得"""
    replies = []
    cursor = None
    
    while True:
        try:
            # スレッド返信を取得
            response = call_slack_api_with_retry(
                client,
                "conversations_replies",
                channel=channel_id,
                ts=thread_ts,
                limit=limit,
                cursor=cursor
            )
            
            batch = response.get('messages', [])
            # 最初のメッセージ（親メッセージ）を除外
            if batch and len(batch) > 0:
                batch = batch[1:]  # 親メッセージを除外
            
            if batch:  # 空のバッチをチェック
                replies.extend(batch)
            
            # ページネーション処理
            cursor = response.get('response_metadata', {}).get('next_cursor')
            if not cursor:  # カーソルがない場合は終了
                break
                
        except SlackApiError as e:
            logger.error(f"スレッド返信の取得に失敗しました: {e}")
            raise
    
    return replies


def get_user_info(client: WebClient, user_ids: List[str]) -> Dict[str, Dict]:
    """複数のユーザー情報を取得してキャッシュ"""
    user_cache = {}
    
    for user_id in user_ids:
        try:
            if user_id not in user_cache and user_id and user_id != "USLACKBOT":
                response = call_slack_api_with_retry(client, "users_info", user=user_id)
                user = response.get('user', {})
                user_cache[user_id] = {
                    'id': user_id,
                    'name': user.get('name', ''),
                    'real_name': user.get('real_name', ''),
                    'display_name': user.get('profile', {}).get('display_name', '')
                }
        except SlackApiError as e:
            logger.warning(f"ユーザー情報の取得に失敗しました (ID: {user_id}): {e}")
            # エラーがあっても続行、情報がない場合はIDのみ保存
            user_cache[user_id] = {'id': user_id, 'name': '', 'real_name': '', 'display_name': ''}
    
    # Slackbotのデータを追加（APIで取得できない場合がある）
    if "USLACKBOT" in user_ids:
        user_cache["USLACKBOT"] = {
            'id': "USLACKBOT",
            'name': "slackbot",
            'real_name': "Slackbot",
            'display_name': "Slackbot"
        }
    
    return user_cache


def collect_user_ids(messages: List[Dict]) -> List[str]:
    """メッセージからユーザーIDを収集"""
    user_ids = set()
    
    for message in messages:
        # メッセージ投稿者
        if 'user' in message and message['user']:
            user_ids.add(message['user'])
        
        # リアクションのユーザー
        for reaction in message.get('reactions', []):
            user_ids.update([user_id for user_id in reaction.get('users', []) if user_id])
        
        # スレッド返信のユーザー
        for reply in message.get('replies', []):
            if isinstance(reply, dict) and 'user' in reply and reply['user']:
                user_ids.add(reply['user'])
    
    return list(user_ids)


def enrich_message_data(messages: List[Dict], users: Dict[str, Dict]) -> List[Dict]:
    """メッセージデータにユーザー情報を追加"""
    enriched_messages = []
    
    for message in messages:
        # ユーザー情報を追加
        if 'user' in message and message['user'] in users:
            message['user_info'] = users[message['user']]
        
        # リアクションにユーザー情報を追加
        if 'reactions' in message:
            for reaction in message['reactions']:
                enriched_users = []
                for user_id in reaction.get('users', []):
                    if user_id in users:
                        enriched_users.append(users[user_id])
                reaction['user_details'] = enriched_users
        
        # スレッド返信にユーザー情報を追加
        if 'replies' in message and isinstance(message['replies'], list):
            for i, reply in enumerate(message['replies']):
                if isinstance(reply, dict) and 'user' in reply and reply['user'] in users:
                    message['replies'][i]['user_info'] = users[reply['user']]
        
        enriched_messages.append(message)
    
    return enriched_messages


def process_channel_data(client: WebClient, channel_name: str, start_time: float, end_time: float) -> Dict:
    """チャンネルデータの処理メインロジック"""
    # チャンネルIDを取得
    channel_id = get_channel_id(client, channel_name)
    
    # チャンネル情報を取得
    channel_info = call_slack_api_with_retry(client, "conversations_info", channel=channel_id)
    channel_data = channel_info.get('channel', {})
    
    # 指定期間のメッセージを取得
    messages = get_conversation_history(client, channel_id, start_time, end_time)
    if not messages:
        logger.warning(f"指定期間内にメッセージが見つかりませんでした。チャンネル: {channel_name}")
    
    # スレッド返信を取得
    thread_count = 0
    for message in messages:
        if message.get('thread_ts') and message.get('thread_ts') == message.get('ts'):
            # 親メッセージのスレッドIDが自分自身のtsと同じ場合のみ処理
            replies = get_thread_replies(client, channel_id, message['thread_ts'])
            message['replies'] = replies
            thread_count += len(replies)
    
    logger.info(f"メッセージ数: {len(messages)}, スレッド返信数: {thread_count}")
    
    # ユーザーIDを収集
    user_ids = collect_user_ids(messages)
    
    # ユーザー情報を取得
    users = get_user_info(client, user_ids)
    
    # メッセージデータをエンリッチ
    enriched_messages = enrich_message_data(messages, users)
    
    # 結果のJSONを構築
    result = {
        'channel': {
            'id': channel_id,
            'name': channel_name,
            'topic': channel_data.get('topic', {}).get('value', ''),
            'purpose': channel_data.get('purpose', {}).get('value', '')
        },
        'time_range': {
            'start': datetime.datetime.fromtimestamp(start_time, JST).isoformat(),
            'end': datetime.datetime.fromtimestamp(end_time, JST).isoformat()
        },
        'messages': enriched_messages,
        'users': users,
        'metadata': {
            'total_messages': len(messages),
            'total_thread_replies': thread_count,
            'total_unique_users': len(users),
            'export_time': datetime.datetime.now(JST).isoformat(),
            'exporter_version': '1.0.0'
        }
    }
    
    return result


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(description='Slackチャンネルの会話をJSONでエクスポート')
    parser.add_argument('--channel', '-c', required=True, help='エクスポートするSlackチャンネル名')
    parser.add_argument('--token', '-t', required=True, help='SlackのAPIトークン')
    parser.add_argument('--start', '-s', required=True, help='開始時間 (YYYY-MM-DDTHH:mm:ss形式、JST)')
    parser.add_argument('--end', '-e', required=True, help='終了時間 (YYYY-MM-DDTHH:mm:ss形式、JST)')
    parser.add_argument('--output', '-o', default='slack_export.json', help='出力JSONファイル名')
    parser.add_argument('--verbose', '-v', action='store_true', help='詳細なログを出力')
    parser.add_argument('--pretty', '-p', action='store_true', help='整形されたJSONを出力（読みやすいが大きくなります）')
    
    args = parser.parse_args()
    
    # ログレベル設定
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    try:
        # 入力パラメータのバリデーション
        if not args.token:
            raise ValueError("Slack APIトークンが指定されていません")
        
        if not args.token.startswith(('xoxb-', 'xoxp-', 'xoxa-', 'xoxs-')):
            logger.warning("Slack APIトークンの形式が一般的なものとは異なります（xoxb-などで始まる必要があります）")
        
        # 時間文字列をUNIXタイムスタンプに変換
        start_time = parse_datetime(args.start)
        end_time = parse_datetime(args.end)
        
        if start_time >= end_time:
            raise ValueError("開始時間は終了時間より前である必要があります")
        
        # Slackクライアントの初期化
        client = WebClient(token=args.token)
        
        # トークンの有効性を確認（簡易チェック）
        try:
            call_slack_api_with_retry(client, "auth_test")
        except SlackApiError as e:
            if e.response.get('error') == 'invalid_auth':
                raise ValueError("無効なSlack APIトークンです")
            raise
        
        # チャンネルデータの処理
        logger.info(f"'{args.channel}'チャンネルのデータ収集を開始します...")
        result = process_channel_data(client, args.channel, start_time, end_time)
        
        # JSON出力
        logger.info(f"JSONデータを{args.output}に書き込み中...")
        with open(args.output, 'w', encoding='utf-8') as f:
            if args.pretty:
                json.dump(result, f, ensure_ascii=False, indent=2)
            else:
                json.dump(result, f, ensure_ascii=False)
        
        logger.info(f"エクスポート完了！ファイル: {args.output}")
        logger.info(f"合計メッセージ数: {result['metadata']['total_messages']}")
        logger.info(f"スレッド返信数: {result['metadata']['total_thread_replies']}")
        logger.info(f"ユニークユーザー数: {result['metadata']['total_unique_users']}")
        
    except ValueError as e:
        logger.error(f"入力エラー: {e}")
        sys.exit(1)
    except SlackApiError as e:
        logger.error(f"Slack API エラー: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"予期せぬエラーが発生しました: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()