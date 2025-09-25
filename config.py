"""
config.py

Stores all static configuration for the dual-camera fusion vision system.
The camera pipelines have been simplified to offload CLAHE processing until after fusion.
"""

# Import the test image generators from their new location in utils.py
from utils import static_test_grid, dynamic_test_image

# --- New, Scalable Configuration Structure ---

CAMERAS = [
    {
        'id': 'cam1',
        'enabled': True,
        'source': static_test_grid,
        'resolution': (1280, 720),
        # The pipeline is now simpler: just grab and find contours.
        'pipeline': ['process_contours'],
        'overlay_color': (255, 0, 0),
    },
    {
        'id': 'cam2',
        'enabled': True,
        'source': dynamic_test_image,
        'resolution': (1280, 720),
        'pipeline': ['process_contours'],
        'overlay_color': (0, 0, 255),
    },
]

# The Fusion worker is also defined in a structured way.
FUSION_CONFIG = {
    'enabled': True,
    'sources': ['cam1', 'cam2'],
    'overlap_trim_x': 48,
    'overlap_trim_y': -48,
    # CLAHE settings are now part of the fusion process, applied by FinalProcessor.
    'clahe_clip_limit': 4.0,
    'clahe_tile_grid_size': (8, 8),
}

# Global processing settings
SATURATION_THRESHOLD = 240

# Web server settings
WEB_SERVER_CONFIG = {
    'port': 5000,
}
