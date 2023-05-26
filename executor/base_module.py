from abc import ABC
from abc import abstractmethod

import torch.nn


class MModule(torch.nn.Module, ABC):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @abstractmethod
    def compute_loss(self, outputs, Y) -> torch.Tensor:
        pass
