import pandas as pd

class GameDataManager:
    REQUIRE_CONFIGS = {
        'building':{},
        'research':{},
        'unit':{},
        'buff':{},
        'item':{},
        'mission':{},
        'mission_index':{}  # 🔥 미션 인덱스 추가
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
        
        cls._load_item_data()
        cls._load_mission_data()
        cls._build_mission_index()  # 🔥 미션 인덱스 자동 생성
        cls._loaded = True
        print("Game data loaded successfully!")
    
    @classmethod
    def _load_building_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/building_info.csv', encoding= 'cp949').fillna("")
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
        df = pd.read_csv('./meta_data/research_info.csv', encoding= 'cp949').fillna("")
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
                'value': row['value'],
                'time': int(row['research_time']),
                'required_researches': requires,  # [(building_idx, level), ...]
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    
    @classmethod
    def _load_unit_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/unit_info.csv', encoding= 'cp949').fillna("")
        
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
        df = pd.read_csv('./meta_data/buff_info.csv', encoding= 'cp949').fillna("")
        
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
                'target_sub_type': row['target_sub_type'],
                'stat_type': row['stat_type'],
                'value_type': row['value_type'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_item_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/item_info.csv', encoding= 'cp949').fillna("")
        
        
        item_configs = cls.REQUIRE_CONFIGS['item']
        
        for _, row in df.iterrows():
            item_idx = int(row['item_idx'])
            if item_idx not in item_configs:
                item_configs[item_idx] = {}
            
            
            item_configs[item_idx] = {
                'item_idx': item_idx,
                'category': row['category'],
                'item_type': row['item_type'],
                'target_type': row['target_type'],
                'value': row['value'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_mission_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df_mission = pd.read_csv('./meta_data/mission_info.csv', encoding= 'cp949').fillna("")
        df_mission_reward = pd.read_csv('./meta_data/mission_reward.csv', encoding= 'cp949').fillna("")
        
        mission_configs = cls.REQUIRE_CONFIGS['mission']
        
        for _, row in df_mission.iterrows():
            mission_idx = int(row['mission_idx'])
            if mission_idx not in mission_configs:
                mission_configs[mission_idx] = {}
            
            df_mission_reward_range = df_mission_reward[df_mission_reward['mission_idx'] == mission_idx]
            
            df_mission_reward_dic = {int(row['item_idx']): int(row['value']) for i, row in df_mission_reward_range.iterrows()}
            
            mission_configs[mission_idx] = {
                'mission_idx': mission_idx,
                'category': row['category'],
                'target_idx': int(row['target_idx']),  # int로 변환
                'value': int(row['value']),
                'required_missions': row['required_missions'],
                'reward': df_mission_reward_dic,    
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _build_mission_index(cls):
        """
        🔥 미션 Config로부터 인덱스 자동 생성
        
        생성되는 구조:
        {
            "building": {201: [101001, 101002], 202: [101003]},
            "unit": {401: [102001, 102002]},
            "research": {1001: [103001]},
            "hero": {1001: [104001]}
        }
        """
        print("Building mission index...")
        
        mission_configs = cls.REQUIRE_CONFIGS['mission']
        mission_index = cls.REQUIRE_CONFIGS['mission_index']
        
        # 카테고리 초기화
        categories = ['building', 'unit', 'research', 'hero', 'battle', 'resource']
        for category in categories:
            mission_index[category] = {}
        
        # 미션 순회하며 인덱스 생성
        mission_count = 0
        for mission_idx, mission in mission_configs.items():
            category = mission.get('category')
            target_idx = mission.get('target_idx')
            
            if not category or target_idx is None:
                print(f"⚠️  Warning: Mission {mission_idx} has no category or target_idx")
                continue
            
            # 카테고리가 없으면 추가
            if category not in mission_index:
                mission_index[category] = {}
            
            # target_idx를 int로 변환 (string일 수도 있음)
            try:
                target_key = int(target_idx)
            except (ValueError, TypeError):
                target_key = target_idx
            
            # target_idx별로 미션 그룹핑
            if target_key not in mission_index[category]:
                mission_index[category][target_key] = []
            
            mission_index[category][target_key].append(mission_idx)
            mission_count += 1
        
        # 통계 출력
        print(f"✅ Mission index built successfully!")
        print(f"   Total missions indexed: {mission_count}")
        for category, targets in mission_index.items():
            if targets:
                mission_count_in_category = sum(len(missions) for missions in targets.values())
                print(f"   - {category}: {len(targets)} targets, {mission_count_in_category} missions")
        
        # 예시 출력 (디버깅용)
        if mission_index.get('building'):
            first_building = list(mission_index['building'].keys())[0]
            print(f"   Example: building[{first_building}] = {mission_index['building'][first_building]}")
    
    
    
    @classmethod
    def _convert_required(cls, row, columns):
        requires = []
        require_str = str(row.get(columns, '')).strip()
        if require_str and require_str != 'nan':
                for req in require_str.split(','):
                    if ':' in req:
                        idx, lv = req.strip().split('_')
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
        print(cls.REQUIRE_CONFIGS)
        return {
            "success": True,
            "message": "Loaded REQUIRE_CONFIGS",
            "data": cls.REQUIRE_CONFIGS
        }