import yaml
from pathlib import Path
from urllib.parse import urlencode
from arac_eksper.schemas import SearchCriteria

def load_category_map():
    path = Path(__file__).parent.parent / "config" / "category_map.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
        return data.get("categories", {}) if data else {}

def get_category_slug(criteria: SearchCriteria) -> str:
    """Harita biçimi: Marka -> Model -> "slug"  ya da  Marka -> Model -> {"_model": "slug", "<seri>": "slug"}.
    Seri verilmişse ve haritada varsa seri slug'ı, yoksa model slug'ı kullanılır."""
    cmap = load_category_map()
    model_map = cmap.get(criteria.marka, {}).get(criteria.model, "")
    if isinstance(model_map, str):
        return model_map
    if isinstance(model_map, dict):
        if criteria.seri and criteria.seri in model_map:
            return model_map[criteria.seri]
        return model_map.get("_model", "")
    return ""

def build_search_url(criteria: SearchCriteria, page: int = 1, sort: str = "date_desc") -> str:
    slug = get_category_slug(criteria)
    if not slug:
        raise ValueError(f"Kategori haritasında {criteria.marka} {criteria.model} bulunamadı.")
        
    base_url = f"https://www.sahibinden.com/{slug}"
    
    params = {}
    if criteria.min_butce: params["price_min"] = criteria.min_butce
    if criteria.max_butce: params["price_max"] = criteria.max_butce
    if criteria.min_yil: params["a5_min"] = criteria.min_yil
    if criteria.max_km: params["a4_max"] = criteria.max_km
    
    if criteria.il: params["address_city"] = 1 # Burada il map'i de olmalı aslında, basit tuttuk
    
    if criteria.kimden == "sahibinden": params["a106195"] = "113840"
    elif criteria.kimden == "galeriden": params["a106195"] = "113841"
    
    if sort == "date_desc": params["sorting"] = "date_desc"
    if page > 1: params["pagingOffset"] = (page - 1) * 20
    
    query = urlencode(params)
    return f"{base_url}?{query}" if query else base_url
