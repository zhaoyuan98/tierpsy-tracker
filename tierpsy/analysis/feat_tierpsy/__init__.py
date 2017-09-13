from .get_tierpsy_features import get_tierpsy_features

def args_(fn, param):
  # getWormFeatures
  main_func = get_tierpsy_features
  requirements = ['FEAT_INIT']
  
  #arguments used by AnalysisPoints.py
  return {
        'func': main_func,
        'argkws': {
                  'features_file': fn['featuresN']
                  },
        'input_files' : [fn['featuresN']],
        'output_files': [fn['featuresN']],
        'requirements' : requirements
    }

    