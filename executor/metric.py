from typing import List, Dict
from data import Graph
import numpy as np

class MetricUtil:
    @staticmethod
    def compute_duration_metrics(graphs: List[Graph], graph_id_to_duration_pred: Dict[str, float]) -> Dict:
        y_hat, y = list(), list()
        for graph in graphs:
            pred = graph_id_to_duration_pred[graph.ID]
            ground_truth = graph.graph_duration
            y_hat.append(pred)
            y.append(ground_truth)
        y_hat = np.array(y_hat)
        y = np.array(y)
        MRE = np.sum(np.abs(y - y_hat) / y) / len(y)
        RMSE = np.sqrt(np.sum(np.power(y - y_hat, 2)) / len(y))
        return {
            "MRE": MRE,
            "RMSE": RMSE
        }