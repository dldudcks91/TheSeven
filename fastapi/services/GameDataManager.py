import pandas as pd

class GameDataManager:
    REQUIRE_CONFIGS = {
        'building':{},
        'research':{},
        'unit':{},
        'buff':{}
        }
    _loaded = False
    
    @classmethod
    def initialize(cls):
        """서버 시작시 딱 한번만 실행"""
        if cls._loaded:
            return
            
        print("Loading game data from CSV...")
        cls._load_building_data()
        cls._load_unit_data()
        cls._load_buff_data()
        cls._loaded = True
        print("Game data loaded successfully!")
    
    @classmethod
    def _load_building_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/building_info.csv')
        building_configs = cls.REQUIRE_CONFIGS['building']
        
        for _, row in df.iterrows():
            building_idx = row['building_idx']
            building_lv = row['building_lv']
            
            if building_idx not in building_configs:
                building_configs[building_idx] = {}
                
            requires = []
            require_str = str(row.get('required_building', '')).strip()
            if require_str and require_str != 'nan':
                    for req in require_str.split(','):
                        if ':' in req:
                            idx, lv = req.strip().split(':')
                            requires.append((int(idx), int(lv)))
                            
            building_configs[building_idx][building_lv] = {
                'cost': {'food_cost': int(row['food_cost']), 'wood_cost': int(row['wood_cost']),'stone_cost': int(row['stone_cost']),'gold_cost': int(row['gold_cost'])},
                'time': int(row['construct_time']),
                'required_buildings': requires,  # [(building_idx, level), ...]
                'description': row['description']
            }
            
    @classmethod
    def _load_unit_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/unit_info.csv', encoding= 'cp949')
        
        unit_configs = cls.REQUIRE_CONFIGS['unit']
        
        for _, row in df.iterrows():
            unit_idx = row['unit_idx']
            if unit_idx not in unit_configs:
                unit_configs[unit_idx] = {}
                
            
            unit_configs[unit_idx] = {
                'unit_idx': unit_idx,
                'unit_tier': row['unit_tier'],
                'time': int(row['train_time']),
                'cost': {'food_cost': int(row['food_cost']), 'wood_cost': int(row['wood_cost']),'stone_cost': int(row['stone_cost']),'gold_cost': int(row['gold_cost'])},
                'ability':{'attack':int(row['attack']),'defense': int(row['defense']), 'health': int(row['health']), 'speed': int(row['speed'])},
                'category': row['category'],
                'description': row['description']
            }
    
    @classmethod
    def _load_buff_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/buff_info.csv', encoding= 'cp949')
        
        buff_configs = cls.REQUIRE_CONFIGS['buff']
        
        for _, row in df.iterrows():
            buff_idx = row['buff_idx']
            if buff_idx not in buff_configs:
                buff_configs[buff_idx] = {}
                
            
            buff_configs[buff_idx] = {
                'buff_idx': buff_idx,
                'category': row['category'],
                'calculate_type': row['calculate_type'],
                'buff_effect': int(row['buff_effect']),
                'time': int(row['buff_time']),
                'description': row['description']
            }
    
    
    @classmethod
    def get_upgrade_requirements(cls, building_idx, current_level):
        """메모리에서 즉시 조회 (I/O 없음!)"""
        next_level = current_level + 1
        return cls._building_configs.get(building_idx, {}).get(next_level)
    
    