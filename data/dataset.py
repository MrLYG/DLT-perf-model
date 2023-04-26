import pathlib
from abc import ABC, abstractmethod
from collections import defaultdict
from functools import lru_cache
from itertools import count
from typing import List, Tuple, Union, Callable, Optional, Dict

import numpy as np
import torch
from sklearn import preprocessing
from torch.utils.data import Dataset

from objects import Environment, DatasetType
from .graph import Graph, FeatureKeys
from .util import datasets_path, Normalizer


class MDataset(ABC, Dataset):
    def __init__(self, graphs_cache_key: str, features: List[Dict], labels: List[Dict], normalization: Union[str, Callable] = "standard"):
        self.graphs_cache_key: str = graphs_cache_key
        self.features = features
        self.labels = labels
        self.normalizer: Optional[Normalizer] = None
        if isinstance(normalization, str):
            self._init_normalizer(normalization)
        elif callable(normalization):
            self.normalizer = normalization
        else:
            raise ValueError("Invalid normalization. Normalization must be a string or a callable object.")

    def _init_normalizer(self, normalization: str):
        if normalization == "Standard":
            self._init_normalizer_impl(preprocessing.StandardScaler)
        elif normalization == "MinMax":
            self._init_normalizer_impl(preprocessing.MinMaxScaler)
        else:
            raise ValueError("Invalid normalization. string normalization must be 'standard', 'MinMax'.")

    @abstractmethod
    def _init_normalizer_impl(self, scaler_class):
        pass

    @classmethod
    def _get_y_scaler_dict(cls, labels, scaler_class):
        y_scaler_dict = dict()
        y_sample = labels[0]
        y_keys = y_sample.keys()
        for key in y_keys:
            if key not in [FeatureKeys.Y_OP_FEAT, FeatureKeys.Y_SUBGRAPH_FEAT]:
                y_scaler_dict[key] = lambda item: item
                continue
            if key == FeatureKeys.Y_SUBGRAPH_FEAT:
                subgraph_feature = list(y[key] for y in labels)
                subgraph_feature_scaler = scaler_class()
                subgraph_feature_scaler.fit(subgraph_feature)
                y_scaler_dict[key] = subgraph_feature_scaler
                continue
            assert key == FeatureKeys.Y_OP_FEAT
            y_op_features = list()
            for y in labels:
                for op_feature in y[FeatureKeys.Y_OP_FEAT]:
                    y_op_features.append(op_feature)
            op_feature_scaler = scaler_class()
            op_feature_scaler.fit(y_op_features)
            y_scaler_dict[key] = lambda Y: [op_feature_scaler(y) for y in Y]
        return y_scaler_dict

    @staticmethod
    def data_collator(samples: List[Dict]) -> Dict:
        batch = dict()
        for sample in samples:
            for k, v in sample.items():
                if k == "label":
                    batch.setdefault("labels", dict())
                    for vk, vv in v.items():
                        batch["labels"].setdefault(vk, list())
                        batch["labels"][vk].append(vv)
                else:
                    batch.setdefault(k, list())
                    batch[k].append(v)

        def make_tensor(d):
            for k_, v_ in d.items():
                if isinstance(v_, dict):
                    make_tensor(v_)
                    continue
                v_ = np.array(v_)
                if not k_.endswith(FeatureKeys.FEAT_SUFFIX):
                    d[k_] = v_
                    continue
                d[k_] = torch.tensor(v_, dtype=torch.float32)

        make_tensor(batch)
        return batch

    def __len__(self):
        return len(self.features)

    def __getitem__(self, index):
        x = self.features[index]
        y = self.labels[index]

        if self.normalizer:
            x, y = self.normalizer(x, y)

        item = {key: val for key, val in x.items()}
        item['label'] = y
        return item

    def get_normalizer(self) -> Callable:
        return self.normalizer


class SubgraphDataset(MDataset):
    def _init_normalizer_impl(self, scaler_class):
        x_scaler_dict = dict()
        group_features = list()
        x_sample = self.features[0]
        x_keys = x_sample.keys()
        for k in x_keys:
            if k != FeatureKeys.X_SUBGRAPH_FEAT:
                x_scaler_dict[k] = lambda item: item
                continue
            for x in self.features:
                group_feature = x[FeatureKeys.X_SUBGRAPH_FEAT]
                group_features.extend(group_feature)
            group_feature_scaler = scaler_class()
            group_feature_scaler.fit(group_features)
            x_scaler_dict[FeatureKeys.X_SUBGRAPH_FEAT] = lambda Y: [group_feature_scaler(y) for y in Y]

        y_scaler_dict = self._get_y_scaler_dict(self.labels, scaler_class)

        return Normalizer(x_scaler_dict, y_scaler_dict)


class OPDataset(MDataset):
    def _init_normalizer_impl(self, scaler_class):
        x_scaler_dict = dict()
        x_op_features = list()
        x_sample = self.features[0]
        x_keys = x_sample.keys()
        for k in x_keys:
            if k != FeatureKeys.X_OP_FEAT:
                x_scaler_dict[k] = lambda item: item
                continue
            assert k == FeatureKeys.X_OP_FEAT
            for x in self.features:
                op_feature = x[FeatureKeys.X_OP_FEAT]
                x_op_features.append(op_feature)
            x_op_feature_scaler = scaler_class()
            x_op_feature_scaler.fit(x_op_features)
            x_scaler_dict[FeatureKeys.X_SUBGRAPH_FEAT] = x_op_feature_scaler

        y_scaler_dict = self._get_y_scaler_dict(self.labels, scaler_class)

        return Normalizer(x_scaler_dict, y_scaler_dict)


class DatasetFactory:
    graphs_cache = dict()

    @staticmethod
    @lru_cache(maxsize=None)
    def _load_graphs(environment: Environment, train_or_val: str = "train", dummy: bool = False) -> List[Graph]:
        if dummy:
            return list(Graph.from_data(None, dummy=True) for _ in range(100))
        data_dir = pathlib.Path(datasets_path) / f"{environment}"
        # Load data from directory
        return list()

    @staticmethod
    def create_dataset(environment: Environment,
                       normalization: str,
                       dataset_type: DatasetType = DatasetType.Subgraph,
                       dummy: bool = False,
                       **kwargs) -> Tuple[MDataset, MDataset]:
        dataset_creator = {
            DatasetType.OP: DatasetFactory._create_op_dataset,
            DatasetType.Grouping: DatasetFactory._create_graph_grouping_dataset,
            DatasetType.Subgraph: DatasetFactory._create_subgraph_dataset,
        }
        creator = dataset_creator[dataset_type]
        train_graphs_cache_key = DatasetFactory._graphs_cache_key(environment, "train", dummy)
        val_graphs_cache_key = DatasetFactory._graphs_cache_key(environment, "val", dummy)
        train_graphs = DatasetFactory.graphs_cache.get(train_graphs_cache_key,
                                                       DatasetFactory._load_graphs(environment, train_or_val="train",
                                                                                   dummy=dummy))
        DatasetFactory.graphs_cache[train_graphs_cache_key] = train_graphs
        val_graphs = DatasetFactory.graphs_cache.get(val_graphs_cache_key,
                                                     DatasetFactory._load_graphs(environment, train_or_val="val",
                                                                                 dummy=dummy))
        DatasetFactory.graphs_cache[val_graphs_cache_key] = val_graphs

        train = creator(train_graphs_cache_key, normalization, **kwargs)
        val = creator(val_graphs_cache_key, normalization, **kwargs)
        return train, val

    @staticmethod
    def _graphs_cache_key(environment, train_or_val: str, dummy: bool) -> str:
        return f"{environment}|{train_or_val}|{dummy}"

    @staticmethod
    @lru_cache(maxsize=None)
    def _create_op_dataset(graphs_cache_key: str,
                           normalization: str,
                           **kwargs) -> OPDataset:
        graphs = DatasetFactory.graphs_cache[graphs_cache_key]
        op_X, op_Y = list(), list()
        data_idx_to_graph = dict()
        counter = iter(count())
        for graph in graphs:
            X, Y = graph.Serial_feature_extractor.node_features()
            op_X.extend(X)
            op_Y.extend(Y)
            for i in range(len(X)):
                data_idx_to_graph[next(counter)] = graph

        dataset = OPDataset(graphs_cache_key, op_X, op_Y, normalization)
        return dataset

    @staticmethod
    @lru_cache(maxsize=None)
    def _create_graph_grouping_dataset(graphs_cache_key: str,
                                       normalization: str,
                                       subgraph_count=10,
                                       **kwargs) -> SubgraphDataset:
        graphs = DatasetFactory.graphs_cache[graphs_cache_key]
        graph_X, graph_Y = list(), list()
        data_idx_to_graph = dict()
        for i, graph in enumerate(graphs):
            x, y = graph.GNN_based_feature_extractor.full_graph_feature(subgraph_count=subgraph_count)
            graph_X.append(x)
            # graph_Y.append(label.subgraph_durations)
            graph_Y.append(y)
            data_idx_to_graph[i] = graph
        dataset = SubgraphDataset(graphs_cache_key, graph_X, graph_Y, normalization)
        return dataset

    @staticmethod
    @lru_cache(maxsize=None)
    def _create_subgraph_dataset(graphs_cache_key: str,
                                 normalization: str,
                                 subgraph_node_size=10,
                                 **kwargs) -> SubgraphDataset:
        graphs = DatasetFactory.graphs_cache[graphs_cache_key]
        subgraph_X, subgraph_Y = list(), list()
        data_idx_to_graph = dict()
        counter = iter(count())
        for graph in graphs:
            X, Y = graph.Serial_feature_extractor.subgraph_features(subgraph_node_size=subgraph_node_size)
            subgraph_X.extend(X)
            # Y = list()
            # for label in labels:
            #     Y.append(label.subgraph_durations)
            #     Y.append(label.node_durations)
            subgraph_Y.extend(Y)
            for i in range(len(X)):
                data_idx_to_graph[next(counter)] = graph
        dataset = SubgraphDataset(graphs_cache_key, subgraph_X, subgraph_Y, normalization)
        return dataset
