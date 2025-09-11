import redis.asyncio as aioredis
import json
from typing import Dict, List, Any, Optional

class RedisDataChecker:
    """비동기 Redis 데이터 체커"""
    
    def __init__(self, host='localhost', port=6379, db=0, password=None):
        """
        Redis 연결 초기화
        
        Args:
            host: Redis 서버 호스트 (기본값: localhost)
            port: Redis 서버 포트 (기본값: 6379)
            db: 데이터베이스 번호 (기본값: 0)
            password: Redis 비밀번호 (있는 경우)
        """
        self.redis_client = None
        self.host = host
        self.port = port
        self.db = db
        self.password = password
    
    async def connect(self):
        """Redis 연결 설정"""
        try:
            self.redis_client = aioredis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True
            )
            # 연결 테스트
            await self.redis_client.ping()
            print(f"✅ Redis 연결 성공: {self.host}:{self.port}")
        except aioredis.ConnectionError as e:
            print(f"❌ Redis 연결 실패: {e}")
            raise
    
    async def close(self):
        """Redis 연결 종료"""
        if self.redis_client:
            await self.redis_client.aclose()
    
    async def get_all_keys(self, pattern='*') -> List[str]:
        """
        모든 키 목록 조회
        
        Args:
            pattern: 키 패턴 (기본값: '*' - 모든 키)
        
        Returns:
            키 목록
        """
        keys = []
        async for key in self.redis_client.scan_iter(match=pattern):
            keys.append(key)
        print(f"📊 총 {len(keys)}개의 키 발견 (패턴: {pattern})")
        return keys
    
    async def get_key_info(self, key: str) -> Dict[str, Any]:
        """
        특정 키의 정보 조회
        
        Args:
            key: 조회할 키
        
        Returns:
            키 정보 딕셔너리
        """
        if not await self.redis_client.exists(key):
            return {"error": f"키 '{key}'가 존재하지 않습니다."}
        
        key_type = await self.redis_client.type(key)
        ttl = await self.redis_client.ttl(key)
        
        # 키 크기 추정
        size = await self._estimate_key_size(key, key_type)
        
        info = {
            "key": key,
            "type": key_type,
            "ttl": ttl if ttl > 0 else "만료시간 없음",
            "size": size
        }
        
        return info
    
    async def _estimate_key_size(self, key: str, key_type: str) -> str:
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
                value = await self.redis_client.get(key)
                return f"~{len(str(value))} bytes" if value else "0 bytes"
            
            elif key_type == 'hash':
                hash_len = await self.redis_client.hlen(key)
                return f"~{hash_len} fields"
            
            elif key_type == 'list':
                list_len = await self.redis_client.llen(key)
                return f"~{list_len} items"
            
            elif key_type == 'set':
                set_len = await self.redis_client.scard(key)
                return f"~{set_len} members"
            
            elif key_type == 'zset':
                zset_len = await self.redis_client.zcard(key)
                return f"~{zset_len} members"
            
            else:
                return "N/A"
                
        except Exception:
            return "N/A"
    
    async def get_value(self, key: str) -> Any:
        """
        키의 값 조회 (타입에 따라 다른 메서드 사용)
        
        Args:
            key: 조회할 키
        
        Returns:
            키의 값
        """
        if not await self.redis_client.exists(key):
            return f"키 '{key}'가 존재하지 않습니다."
        
        key_type = await self.redis_client.type(key)
        
        try:
            if key_type == 'string':
                value = await self.redis_client.get(key)
                # JSON 형태인지 확인
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            
            elif key_type == 'hash':
                return await self.redis_client.hgetall(key)
            
            elif key_type == 'list':
                return await self.redis_client.lrange(key, 0, -1)
            
            elif key_type == 'set':