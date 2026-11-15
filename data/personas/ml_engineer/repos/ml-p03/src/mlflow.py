import mlflow
with mlflow.start_run():
    mlflow.log_metric('mape', mape)
