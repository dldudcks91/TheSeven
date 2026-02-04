#%%
import redis
import json
#%%
redis_client = redis.Redis(
    host='localhost',  # Redis 서버 주소
    port=6379,         # Redis 포트
    db=0,              # 데이터베이스 번호
    decode_responses=True,  # 문자열 응답 자동 디코딩
    socket_connect_timeout=5,  # 연결 타임아웃
    socket_timeout=5,          # 소켓 타임아웃
)
#redis_manager = RedisManager(redis_client)


#redis_client.flushall()
#%%

server_info = redis_client.info()
print("===== Redis 서버 상태 =====")
print(f"서버 버전: {server_info.get('redis_version')}")
print(f"연결된 클라이언트 수: {server_info.get('connected_clients')}")
print(f"사용 메모리: {server_info.get('used_memory_human')}")
print(f"RDB 백업 진행 중: {'Yes' if server_info.get('rdb_bgsave_in_progress') else 'No'}")
print(f"AOF 재작성 진행 중: {'Yes' if server_info.get('aof_rewrite_in_progress') else 'No'}")
print("-" * 20)

"""
Redis 서버에 존재하는 모든 리스트(큐)의 키를 찾고 반환합니다.
주의: KEYS 명령어는 프로덕션 환경에서 성능에 영향을 줄 수 있습니다.
"""
# Redis의 모든 키를 가져옵니다.
# scan_iter를 사용하면 대량의 키를 처리할 때 서버 부하를 줄일 수 있습니다.
all_keys = redis_client.scan_iter(match='*')


zset_keys = dict()
for key in all_keys:
    
    
    key_type = redis_client.type(key)
    
    if zset_keys.get(key_type) is None:
        zset_keys[key_type] = []
    
    zset_keys[key_type].append(key)
    
    
print(zset_keys)
#%%
STRING_KEY = zset_keys['string'][6]
try:
    # HGETALL 명령어 실행: 모든 필드와 값을 딕셔너리로 가져옴
    
    building_data = redis_client.get(STRING_KEY)

    if building_data:
        print(f"✅ {STRING_KEY} 내용 (HGETALL):")
        
        # 딕셔너리 형태로 출력하여 가독성을 높임
        print(json.dumps(building_data, indent=4))
        
        
        
    else:
        print(f"❌ STRING_KEY '{STRING_KEY}'가 존재하지 않거나 비어 있습니다.")

except Exception as e:
    print(f"오류 발생: {e}")

#%%
HASH_KEY = zset_keys['hash'][0]
try:
    # HGETALL 명령어 실행: 모든 필드와 값을 딕셔너리로 가져옴
    building_data = redis_client.hgetall(HASH_KEY)

    if building_data:
        print(f"✅ {HASH_KEY} 내용 (HGETALL):")
        
        # 딕셔너리 형태로 출력하여 가독성을 높임
        print(json.dumps(building_data, indent=4))
        
        
        
    else:
        print(f"❌ Hash Key '{HASH_KEY}'가 존재하지 않거나 비어 있습니다.")

except Exception as e:
    print(f"오류 발생: {e}")

#%%

SET_KEY = zset_keys['set'][0]

# HGETALL 명령어 실행: 모든 필드와 값을 딕셔너리로 가져옴
building_data = redis_client.smembers(SET_KEY)

if building_data:
    print(f"✅ {HASH_KEY} 내용 (HGETALL):")
    
    # 딕셔너리 형태로 출력하여 가독성을 높임
    print(building_data)
        
        
        
    


#%%

'''
Sorted Set
'''

zset_key =  zset_keys['zset'][0]

print(f"\n--- 키: '{zset_key}'의 데이터 ---")
# ZRANGE로 Sorted Set의 모든 멤버와 점수(score)를 조회
# start=0, end=-1 은 전체 범위를 의미
# withscores=True를 사용하면 멤버와 점수를 튜플 형태로 반환
members_with_scores = redis_client.zrange(zset_key, 0, -1, withscores=True)

if not members_with_scores:
    print("  이 키에는 데이터가 없습니다.")
else:
    for member, score in members_with_scores:
        # 멤버(member)는 일반적으로 JSON 문자열이거나 유니크한 ID입니다.
        # 필요에 따라 추가적인 디코딩 또는 파싱이 필요할 수 있습니다.
        # 여기서는 단순히 출력만 합니다.
        print(f"  - 멤버: {member}, 점수(Score): {score}")


            