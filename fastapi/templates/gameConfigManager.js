// gameConfigManager.js
class GameConfigManager {
    static instance = null;
    
    static getInstance() {
        if (!this.instance) {
            this.instance = new GameConfigManager();
        }
        return this.instance;
    }
    
    async loadGameConfig() {
        if (this.config) return this.config; // 이미 로드된 경우 캐시 반환
        
        try {
            const response = await fetch('/api', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_no: 0,
                    api_code: 1002, // GAME_CONFIG_ALL
                    data: {}
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.config = result.data;
                return this.config;
            } else {
                throw new Error(result.message);
            }
        } catch (error) {
            console.error('게임 설정 로드 실패:', error);
            throw error;
        }
    }
    
    
}