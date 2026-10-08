"""Constants for the SHMÚ forecast integration."""

DOMAIN = "shmu"
BASE_URL = "https://www.shmu.sk"
STATIONS_URL = f"{BASE_URL}/api/v1/nwp/getjsonaladinstations"
PRODUCTS_URL = f"{BASE_URL}/api/v1/nwp/getstationproducts"
DATA_URL = f"{BASE_URL}/data/datanwp/json"
CONF_STATION = "station_id"
CONF_MODE = "forecast_mode"
DEFAULT_MODE = "combined"
MODES = ("combined", "aladin", "ecmwf")
MAX_RUN_AGE_HOURS = 48
