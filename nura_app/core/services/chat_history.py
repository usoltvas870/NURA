"""Idempotent Redis chat-history finalization shared by chat adapters."""

import json


CHAT_HISTORY_TTL = 7 * 86400
CHAT_HISTORY_MAX_MESSAGES = 20

_FINALIZE_SCRIPT = """
if redis.call('SISMEMBER', KEYS[2], ARGV[5]) == 1 then return 0 end
local raw = redis.call('GET', KEYS[1])
local history = {}
if raw then
  local ok, decoded = pcall(cjson.decode, raw)
  if ok and type(decoded) == 'table' then history = decoded end
end
for _, entry in ipairs(history) do
  if type(entry) == 'table' and entry.request_key == ARGV[5] then return 0 end
end
table.insert(history, cjson.decode(ARGV[1]))
table.insert(history, cjson.decode(ARGV[2]))
while #history > tonumber(ARGV[3]) do table.remove(history, 1) end
redis.call('SET', KEYS[1], cjson.encode(history), 'EX', ARGV[4])
redis.call('SADD', KEYS[2], ARGV[5])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return 1
"""


def chat_history_key(user_id: object) -> str:
    return f"chat:history:{user_id}"


def chat_history_marker_key(user_id: object) -> str:
    return f"chat:history:finalized:{user_id}"


async def finalize_chat_history_once(redis, *, user_id: object, request_key: str,
                                     user_message: str, assistant_response: str) -> bool:
    """Atomically append a request pair once; marker lifetime matches history TTL."""
    if not assistant_response or not assistant_response.strip():
        raise ValueError("chat_history_empty_assistant_response")
    result = await redis.eval(
        _FINALIZE_SCRIPT,
        2,
        chat_history_key(user_id),
        chat_history_marker_key(user_id),
        json.dumps({"role": "user", "content": user_message, "request_key": request_key}, ensure_ascii=False),
        json.dumps({"role": "assistant", "content": assistant_response, "request_key": request_key}, ensure_ascii=False),
        CHAT_HISTORY_MAX_MESSAGES,
        CHAT_HISTORY_TTL,
        request_key,
    )
    return bool(result)
