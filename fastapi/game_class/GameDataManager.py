import pandas as pd

class GameDataManager:
    require_configs = {
        'buildings':{}
        }
    _loaded = False
    
    @classmethod
    def initialize(cls):
        """서버 시작시 딱 한번만 실행"""
        if cls._loaded:
            return
            
        print("Loading game data from CSV...")
        cls._load_building_data()
        cls._loaded = True
        print("Game data loaded successfully!")
    
    @classmethod
    def _load_building_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/meta_data_building.csv')
        building_configs = cls.require_configs['buildings']
        
        for _, row in df.iterrows():
            building_idx = row['building_idx']
            building_lv = row['building_lv']
            
            if building_idx not in building_configs:
                building_configs[building_idx] = {}
                
            require_buildings = []
            require_str = str(row.get('require_building', '')).strip()
            if require_str and require_str != 'nan':
                    for req in require_str.split(','):
                        if ':' in req:
                            idx, lv = req.strip().split(':')
                            require_buildings.append((int(idx), int(lv)))
                            
            building_configs[building_idx][building_lv] = {
                'cost': {'food': int(row['require_food'])},
                'time': int(row['require_time']),
                'require_buildings': require_buildings  # [(building_idx, level), ...]
            }
    
    @classmethod
    def get_upgrade_requirements(cls, building_idx, current_level):
        """메모리에서 즉시 조회 (I/O 없음!)"""
        next_level = current_level + 1
        return cls._building_configs.get(building_idx, {}).get(next_level)