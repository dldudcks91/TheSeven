import pandas as pd

class GameDataManager:
    REQUIRE_CONFIGS = {
        'building':{},
        'research':{},
        'unit':{},
        'buff':{},
        'item':{},
        'mission':{},
        'mission_index':{},  # 🔥 미션 인덱스 추가
        'shop':{},
        'alliance_level':{},
        'alliance_position':{},
        'alliance_research':{},
        'alliance_donate':{},
        'hero':{},
        'hero_skill':{},
        'npc':{},
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
        cls._load_shop_data()
        cls._load_alliance_level_data()
        cls._load_alliance_position_data()
        cls._load_alliance_research_data()
        cls._load_alliance_donate_data()
        cls._load_hero_data()
        cls._load_hero_skill_data()
        cls._load_npc_data()
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
                'sub_category': row['sub_category'],
                'value': row['value'],
                'english_name': row['english_name'],
                'korean_name': row['korean_name']
            }
    
    @classmethod
    def _load_shop_data(cls):
        
        
        # CSV 파일 읽기 (한번만!)
        df = pd.read_csv('./meta_data/shop_info.csv', encoding= 'cp949').fillna("")
        
        
        shop_configs = cls.REQUIRE_CONFIGS['shop']
        
        for _, row in df.iterrows():
            item_idx = int(row['item_idx'])
            if item_idx not in shop_configs:
                shop_configs[item_idx] = {}
            
            
            shop_configs[item_idx] = {
                'item_idx': item_idx,
                'weight': int(row['weight'])
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
                print(f"[WARN] Mission {mission_idx} has no category or target_idx")
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
        print(f"[OK] Mission index built successfully!")
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
    def _load_alliance_level_data(cls):
        df = pd.read_csv('./meta_data/alliance_level.csv', encoding='utf-8').fillna("")
        level_configs = cls.REQUIRE_CONFIGS['alliance_level']

        for _, row in df.iterrows():
            level = int(row['level'])
            buff_idx = int(row['buff_idx']) if str(row['buff_idx']).strip() else None
            level_configs[level] = {
                'required_exp': int(row['required_exp']),
                'max_members': int(row['max_members']),
                'buff_idx': buff_idx,
                'buff_value': float(row['buff_value']) if str(row['buff_value']).strip() else 0,
            }

    @classmethod
    def _load_alliance_position_data(cls):
        df = pd.read_csv('./meta_data/alliance_position.csv', encoding='utf-8').fillna("")
        position_configs = cls.REQUIRE_CONFIGS['alliance_position']

        for _, row in df.iterrows():
            position = int(row['position'])
            position_configs[position] = {
                'name': row['name'],
                'can_kick': bool(int(row['can_kick'])),
                'can_promote': bool(int(row['can_promote'])),
                'can_invite': bool(int(row['can_invite'])),
                'can_set_join_type': bool(int(row['can_set_join_type'])),
                'can_disband': bool(int(row['can_disband'])),
                'can_notice': bool(int(row['can_notice'])),
            }

    @classmethod
    def _load_alliance_research_data(cls):
        df = pd.read_csv('./meta_data/alliance_research.csv', encoding='utf-8').fillna("")
        research_configs = cls.REQUIRE_CONFIGS['alliance_research']

        for _, row in df.iterrows():
            research_idx = int(row['research_idx'])
            level = int(row['level'])
            if research_idx not in research_configs:
                research_configs[research_idx] = {}
            buff_idx = int(row['buff_idx']) if str(row['buff_idx']).strip() else None
            research_configs[research_idx][level] = {
                'required_exp': int(row['required_exp']),
                'buff_idx': buff_idx,
                'buff_value': float(row['buff_value']) if str(row['buff_value']).strip() else 0,
                'english_name': row['english_name'],
                'korean_name': row['korean_name'],
            }

    @classmethod
    def _load_alliance_donate_data(cls):
        df = pd.read_csv('./meta_data/alliance_donate.csv', encoding='utf-8').fillna("")
        donate_configs = cls.REQUIRE_CONFIGS['alliance_donate']

        for _, row in df.iterrows():
            resource_type = row['resource_type']
            donate_configs[resource_type] = {
                'exp_ratio': int(row['exp_ratio']),
                'coin_ratio': int(row['coin_ratio']),
            }
            coin_item_idx_val = int(row['coin_item_idx']) if str(row['coin_item_idx']).strip() else 0
            if coin_item_idx_val and 'coin_item_idx' not in donate_configs:
                donate_configs['coin_item_idx'] = coin_item_idx_val

    @classmethod
    def _load_hero_data(cls):
        df = pd.read_csv('./meta_data/hero_info.csv', encoding='utf-8').fillna("")
        hero_configs = cls.REQUIRE_CONFIGS['hero']

        for _, row in df.iterrows():
            hero_idx = int(row['hero_idx'])
            hero_configs[hero_idx] = {
                'hero_idx': hero_idx,
                'korean_name': row['korean_name'],
                'english_name': row['english_name'],
                'base_attack': int(row['base_attack']),
                'base_defense': int(row['base_defense']),
                'base_health': int(row['base_health']),
                'atk_growth': int(row['atk_growth']),
                'def_growth': int(row['def_growth']),
                'hp_growth': int(row['hp_growth']),
            }

    @classmethod
    def _load_hero_skill_data(cls):
        df = pd.read_csv('./meta_data/hero_skill.csv', encoding='utf-8').fillna("")
        skill_configs = cls.REQUIRE_CONFIGS['hero_skill']

        for _, row in df.iterrows():
            skill_idx = int(row['skill_idx'])
            skill_configs[skill_idx] = {
                'skill_idx': skill_idx,
                'hero_idx': int(row['hero_idx']),
                'korean_name': row['korean_name'],
                'english_name': row['english_name'],
                'trigger_type': row['trigger_type'],
                'trigger_value': int(row['trigger_value']),
                'effect_type': row['effect_type'],
                'value': float(row['value']),
            }

    @classmethod
    def _load_npc_data(cls):
        df = pd.read_csv('./meta_data/npc_info.csv', encoding='utf-8').fillna("")
        npc_configs = cls.REQUIRE_CONFIGS['npc']

        for _, row in df.iterrows():
            npc_id = int(row['npc_id'])
            # units 파싱: "1:20|2:10" → {1: 20, 2: 10}
            units = {}
            units_str = str(row['units']).strip()
            if units_str:
                for pair in units_str.split('|'):
                    if ':' in pair:
                        uid, cnt = pair.strip().split(':')
                        units[int(uid)] = int(cnt)
            npc_configs[npc_id] = {
                'npc_id': npc_id,
                'korean_name': row['korean_name'],
                'english_name': row['english_name'],
                'tier': int(row['tier']),
                'units': units,
                'exp_reward': int(row['exp_reward']),
                'respawn_minutes': int(row['respawn_minutes']),
                'map_x': int(row['map_x']),
                'map_y': int(row['map_y']),
            }

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