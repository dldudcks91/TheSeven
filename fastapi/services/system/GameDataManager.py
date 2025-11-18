import pandas as pd

class GameDataManager:
    REQUIRE_CONFIGS = {
        'building':{},
        'research':{},
        'unit':{},
        'buff':{},
        'item':{},
        'mission':{}
        }
    _loaded = False
    
    @classmethod
    def initialize(cls):
        """서버 시작시 딱 한번만 실행"""
        if cls._loaded:
            return
            
        print("Loading game data from CSV...")
        cls._load_building_data()
        cls._load_research_data()
        cls._load_unit_data()
        cls._load_buff_data()
        cls._loaded = True
        print("Game data loaded successfully!")
    
    @classmethod
    def _load_building_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/building_info.csv', encoding= 'cp949')
        building_configs = cls.REQUIRE_CONFIGS['building']
        
        for _, row in df.iterrows():
            building_idx = row['building_idx']
            building_lv = row['building_lv']
            
            if building_idx not in building_configs:
                building_configs[building_idx] = {}
                
            requires = cls._convert_required(row, 'required_buildings')
                            
            building_configs[building_idx][building_lv] = {
                'cost': {'food': int(row['food']), 'wood': int(row['wood']),'stone': int(row['stone']),'gold': int(row['gold'])},
                'time': int(row['construct_time']),
                'required_buildings': requires,  # [(building_idx, level), ...]
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_research_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/research_info.csv', encoding= 'cp949')
        research_configs = cls.REQUIRE_CONFIGS['research']
        
        for _, row in df.iterrows():
            
            research_idx = row['research_idx']
            research_lv = row['research_lv']
            
            if research_idx not in research_configs:
                research_configs[research_idx] = {}
                
            
            requires = cls._convert_required(row, 'required_researches')
            
                            
            research_configs[research_idx][research_lv] = {
                'buff_idx': row['buff_idx'],
                
                'cost': {'food': int(row['food']), 'wood': int(row['wood']),'stone': int(row['stone']),'gold': int(row['gold'])},
                'research_lv':research_lv,
                'time': int(row['research_time']),
                'required_researches': requires,  # [(building_idx, level), ...]
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
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
            
            requires = cls._convert_required(row, 'required_researches')
            
            unit_configs[unit_idx] = {
                'unit_idx': unit_idx,
                'unit_tier': row['unit_tier'],
                'time': int(row['train_time']),
                'cost': {'food': int(row['food']), 'wood': int(row['wood']),'stone': int(row['stone']),'gold': int(row['gold'])},
                'ability':{'attack':int(row['attack']),'defense': int(row['defense']), 'health': int(row['health']), 'speed': int(row['speed'])},
                'required_researches': requires,
                'category': row['category'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name'],
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
                'buff_type': row['buff_type'],
                'effect_type': row['effect_type'],
                'target_type': row['target_type'],
                'target_id': row['target_id'],
                'stat_type': row['stat_type'],
                'value': row['value'],
                'value_type': row['value_type'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_item_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/item_info.csv', encoding= 'cp949')
        
        
        item_configs = cls.REQUIRE_CONFIGS['item']
        
        for _, row in df.iterrows():
            item_idx = row['item_idx']
            if item_idx not in item_configs:
                item_configs[item_idx] = {}
            
            
            
            
            
            item_configs[item_idx] = {
                'item_idx': item_idx,
                'category': row['category'],
                'type': row['type'],
                'target': row['target'],
                'value': row['value'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_mission_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df_mission = pd.read_csv('./meta_data/mission_info.csv', encoding= 'cp949')
        df_mission_reward = pd.read_csv('./meta_data/mission_reward.csv', encoding= 'cp949')
        
        mission_configs = cls.REQUIRE_CONFIGS['mission']
        
        for _, row in df_mission.iterrows():
            mission_idx = row['mission_idx']
            if mission_idx not in mission_configs:
                mission_configs[mission_idx] = {}
            
            df_mission_reward_range = df_mission_reward[df_mission_reward['mission_idx'] == mission_idx]
            
            df_mission_reward_dic = {row['item_idx']: row['value'] for i, row in df_mission_reward_range.iterrows()}
            
            mission_configs[mission_idx] = {
                'mission_idx': mission_idx,
                'category': row['category'],
                'target_idx': row['target_idx'],
                'value': row['value'],
                'target_id': row['target_id'],
                'required_missions': row['required_missions'],
                'reward': df_mission_reward_dic,    
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    
    
    @classmethod
    def _convert_required(cls, row, columns):
        requires = []
        require_str = str(row.get(columns, '')).strip()
        if require_str and require_str != 'nan':
                for req in require_str.split(','):
                    if ':' in req:
                        idx, lv = req.strip().split(':')
                        requires.append((int(idx), int(lv)))
                        
        return requires
    
    @classmethod
    def get_upgrade_requirements(cls, building_idx, current_level):
        """메모리에서 즉시 조회 (I/O 없음!)"""
        next_level = current_level + 1
        return cls._building_configs.get(building_idx, {}).get(next_level)
    
    @classmethod
    def get_all_configs(cls):
        """
        모든 로드된 게임 설정(REQUIRE_CONFIGS)을 API 응답 형식으로 반환
        API Code: 1002 (GAME_CONFIG_ALL)에 대응
        """
        return {
            "success": True,
            "message": "Loaded REQUIRE_CONFIGS",
            "data": cls.REQUIRE_CONFIGS
        }