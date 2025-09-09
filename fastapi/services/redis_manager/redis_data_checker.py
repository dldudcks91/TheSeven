import redis
import json
from typing import Dict, List, Any, Optional

class RedisDataChecker:
    def __init__(self, host='localhost', port=6379, db=0, password=None):
        """
        Redis 연결 초기화
        
        Args:
            host: Redis 서버 호스트 (기본값: localhost)
            port: Redis 서버 포트 (기본값: 6379)
            db: 데이터베이스 번호 (기본값: 0)
            password: Redis 비밀번호 (있는 경우)
        """
        try:
            self.redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password,
                decode_responses=True
            )
            # 연결 테스트
            self.redis_client.ping()
            print(f"✅ Redis 연결 성공: {host}:{port}")
        except redis.ConnectionError as e:
            print(f"❌ Redis 연결 실패: {e}")
            raise
    
    def get_all_keys(self, pattern='*') -> List[str]:
        """
        모든 키 목록 조회
        
        Args:
            pattern: 키 패턴 (기본값: '*' - 모든 키)
        
        Returns:
            키 목록
        """
        keys = self.redis_client.keys(pattern)
        print(f"📊 총 {len(keys)}개의 키 발견 (패턴: {pattern})")
        return keys
    
    def get_key_info(self, key: str) -> Dict[str, Any]:
        """
        특정 키의 정보 조회
        
        Args:
            key: 조회할 키
        
        Returns:
            키 정보 딕셔너리
        """
        if not self.redis_client.exists(key):
            return {"error": f"키 '{key}'가 존재하지 않습니다."}
        
        key_type = self.redis_client.type(key)
        ttl = self.redis_client.ttl(key)
        
        # 키 크기 추정
        size = self._estimate_key_size(key, key_type)
        
        info = {
            "key": key,
            "type": key_type,
            "ttl": ttl if ttl > 0 else "만료시간 없음",
            "size": size
        }
        
        return info
    
    def _estimate_key_size(self, key: str, key_type: str) -> str:
        """
        키 크기 추정
        
        Args:
            key: 키 이름
            key_type: 키 타입
        
        Returns:
            추정 크기 문자열
        """
        try:
            if key_type == 'string':
                value = self.redis_client.get(key)
                return f"~{len(str(value))} bytes" if value else "0 bytes"
            
            elif key_type == 'hash':
                hash_len = self.redis_client.hlen(key)
                return f"~{hash_len} fields"
            
            elif key_type == 'list':
                list_len = self.redis_client.llen(key)
                return f"~{list_len} items"
            
            elif key_type == 'set':
                set_len = self.redis_client.scard(key)
                return f"~{set_len} members"
            
            elif key_type == 'zset':
                zset_len = self.redis_client.zcard(key)
                return f"~{zset_len} members"
            
            else:
                return "N/A"
                
        except Exception:
            return "N/A"
    
    def get_value(self, key: str) -> Any:
        """
        키의 값 조회 (타입에 따라 다른 메서드 사용)
        
        Args:
            key: 조회할 키
        
        Returns:
            키의 값
        """
        if not self.redis_client.exists(key):
            return f"키 '{key}'가 존재하지 않습니다."
        
        key_type = self.redis_client.type(key)
        
        try:
            if key_type == 'string':
                value = self.redis_client.get(key)
                # JSON 형태인지 확인
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            
            elif key_type == 'hash':
                return self.redis_client.hgetall(key)
            
            elif key_type == 'list':
                return self.redis_client.lrange(key, 0, -1)
            
            elif key_type == 'set':
                return list(self.redis_client.smembers(key))
            
            elif key_type == 'zset':
                return self.redis_client.zrange(key, 0, -1, withscores=True)
            
            else:
                return f"지원하지 않는 타입: {key_type}"
                
        except Exception as e:
            return f"값 조회 중 오류 발생: {e}"
    
    def print_key_summary(self, keys: List[str], limit: int = 10):
        """
        키 요약 정보 출력
        
        Args:
            keys: 키 목록
            limit: 출력할 최대 키 개수
        """
        print(f"\n🔍 키 요약 정보 (최대 {limit}개):")
        print("-" * 80)
        
        for i, key in enumerate(keys[:limit]):
            info = self.get_key_info(key)
            print(f"{i+1:2d}. 키: {key}")
            print(f"    타입: {info.get('type', 'N/A')}")
            print(f"    TTL: {info.get('ttl', 'N/A')}")
            print(f"    크기: {info.get('size', 'N/A')}")
            print()
        
        if len(keys) > limit:
            print(f"... 총 {len(keys) - limit}개 키 더 있음")
    
    def print_key_value(self, key: str):
        """
        특정 키의 값을 보기 좋게 출력
        
        Args:
            key: 출력할 키
        """
        info = self.get_key_info(key)
        value = self.get_value(key)
        
        print(f"\n🔑 키: {key}")
        print(f"📋 타입: {info.get('type', 'N/A')}")
        print(f"⏰ TTL: {info.get('ttl', 'N/A')}")
        print(f"📏 크기: {info.get('size', 'N/A')}")
        print(f"📄 값:")
        
        if isinstance(value, dict):
            print(json.dumps(value, indent=2, ensure_ascii=False))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                print(f"  {i}: {item}")
        else:
            print(f"  {value}")
        print("-" * 50)
    
    def search_keys_by_pattern(self, pattern: str) -> List[str]:
        """
        패턴으로 키 검색
        
        Args:
            pattern: 검색 패턴 (예: user:*, session:*, *cache*)
        
        Returns:
            매치되는 키 목록
        """
        keys = self.redis_client.keys(pattern)
        print(f"🔍 패턴 '{pattern}'으로 {len(keys)}개 키 발견")
        return keys
    
    def get_database_info(self):
        """
        Redis 데이터베이스 정보 출력
        """
        info = self.redis_client.info()
        
        print("\n📊 Redis 데이터베이스 정보:")
        print(f"Redis 버전: {info.get('redis_version', 'N/A')}")
        print(f"연결된 클라이언트: {info.get('connected_clients', 'N/A')}")
        print(f"사용 메모리: {info.get('used_memory_human', 'N/A')}")
        print(f"총 키 개수: {info.get('db0', {}).get('keys', 0) if 'db0' in info else 0}")
        print(f"만료된 키: {info.get('db0', {}).get('expires', 0) if 'db0' in info else 0}")


def main():
    """
    메인 함수 - 사용 예제
    """
    try:
        # Redis 연결 (필요에 따라 연결 정보 수정)
        checker = RedisDataChecker(
            host='localhost',
            port=6379,
            db=0,
            # password='your_password'  # 비밀번호가 있는 경우
        )
        
        # 데이터베이스 정보 출력
        checker.get_database_info()
        
        # 모든 키 조회
        all_keys = checker.get_all_keys()
        
        # 키 요약 정보 출력
        if all_keys:
            checker.print_key_summary(all_keys, limit=5)
            
            # 첫 번째 키의 상세 정보 출력
            print(f"\n📝 첫 번째 키 '{all_keys[0]}'의 상세 정보:")
            checker.print_key_value(all_keys[0])
        
        # 특정 패턴으로 키 검색 예제
        print("\n🔍 패턴 검색 예제:")
        session_keys = checker.search_keys_by_pattern('session:*')
        user_keys = checker.search_keys_by_pattern('user:*')
        cache_keys = checker.search_keys_by_pattern('*cache*')
        
        # 특정 키 값 조회 예제
        specific_key = input("\n특정 키의 값을 조회하려면 키 이름을 입력하세요 (Enter로 스킵): ").strip()
        if specific_key:
            checker.print_key_value(specific_key)
            
    except Exception as e:
        print(f"오류 발생: {e}")


#if __name__ == "__main__":
#    main()
    
    
checker = RedisDataChecker()
keys = checker.get_all_keys()

checker.print_key_summary(keys)
checker.print_key_value(keys[1])