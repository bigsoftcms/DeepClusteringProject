from pathlib import Path
from pprint import pprint
from typing import Dict, Union, Type, Tuple

from deepclustering.arch import _register_arch
from deepclustering.manager import ConfigManger
from deepclustering.model import Model, to_Apex
from torch.utils.data import DataLoader
from deepclustering.utils import fix_all_seed

import trainer
from resnet_50 import ResNet50

_register_arch("resnet50", ResNet50)

DATA_PATH = Path(".data")
DATA_PATH.mkdir(exist_ok=True)


def get_dataloader(
        config: Dict[str, Union[float, int, dict, str]]
) -> Tuple[DataLoader, DataLoader, DataLoader]:
    """
    We will use config.Config as the input yaml file to select dataset
    config.DataLoader.transforms (naive or strong) to choose data augmentation for GEO
    :param config:
    :return:
    """
    if config.get("Config", DEFAULT_CONFIG).split("_")[-1].lower() == "cifar.yaml":
        from datasets import (
            cifar10_naive_transform as naive_transforms,
            cifar10_strong_transform as strong_transforms,
            Cifar10ClusteringDatasetInterface as DatasetInterface,
        )
        print("Checkout CIFAR10 dataset with transforms:")
        train_split_partition = ["train", "val"]
        val_split_partition = ["train", "val"]
    elif config.get("Config", DEFAULT_CONFIG).split("_")[-1].lower() == "mnist.yaml":
        from datasets import (
            mnist_naive_transform as naive_transforms,
            mnist_strong_transform as strong_transforms,
            MNISTClusteringDatasetInterface as DatasetInterface,
        )
        print("Checkout MNIST dataset with transforms:")
        train_split_partition = ["train", "val"]
        val_split_partition = ["train", "val"]
    elif config.get("Config", DEFAULT_CONFIG).split("_")[-1].lower() == "stl10.yaml":
        from datasets import (
            stl10_strong_transform as strong_transforms,
            stl10_strong_transform as naive_transforms,
            STL10ClusteringDatasetInterface as DatasetInterface,
        )
        train_split_partition = ["train", "test", "train+unlabeled"]
        val_split_partition = ["train", "test"]
        print("Checkout STL-10 dataset with transforms:")
    elif config.get("Config", DEFAULT_CONFIG).split("_")[-1].lower() == "svhn.yaml":
        from datasets import (
            svhn_naive_transform as naive_transforms,
            strong_transforms as strong_transforms,
            SVHNClusteringDatasetInterface as DatasetInterface,
        )
        print("Checkout SVHN dataset with transforms:")
        train_split_partition = ["train", "test"]
        val_split_partition = ["train", "test"]
    else:
        raise NotImplementedError(
            config.get("Config", DEFAULT_CONFIG).split("_")[-1].lower()
        )
    assert config.get("DataLoader").get("transforms"), \
        f"Data augmentation must be provided in config.DataLoader, given {config['DataLoader']}."
    transforms = config.get("DataLoader").get("transforms")
    assert transforms in ("naive", "strong"), f"Only predefined `naive` and `strong` transformations are supported."
    # like a switch statement in python.
    img_transforms = {"naive": naive_transforms, "strong": strong_transforms}.get(transforms)
    assert img_transforms
    print("image transformations:")
    pprint(img_transforms)

    train_loader_A = DatasetInterface(
        data_root=DATA_PATH,
        split_partitions=train_split_partition,
        **{k: v for k, v in merged_config["DataLoader"].items() if k != "transforms"}
    ).ParallelDataLoader(
        img_transforms["tf1"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
    )
    train_loader_B = DatasetInterface(
        data_root=DATA_PATH,
        split_partitions=train_split_partition,
        **{k: v for k, v in merged_config["DataLoader"].items() if k != "transforms"}
    ).ParallelDataLoader(
        img_transforms["tf1"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
        img_transforms["tf2"],
    )
    val_loader = DatasetInterface(
        data_root=DATA_PATH,
        split_partitions=val_split_partition,
        **{k: v for k, v in merged_config["DataLoader"].items() if k != "transforms"}
    ).ParallelDataLoader(img_transforms["tf3"])
    return train_loader_A, train_loader_B, val_loader


def get_trainer(
        config: Dict[str, Union[float, int, dict]]
) -> Type[trainer.ClusteringGeneralTrainer]:
    assert config.get("Trainer").get("name"), config.get("Trainer").get("name")
    trainer_mapping: Dict[str, Type[trainer.ClusteringGeneralTrainer]] = {
        "iicgeo": trainer.IICGeoTrainer,  # the basic iic
        "iicmixup": trainer.IICMixupTrainer,  # the basic IIC with mixup as the data augmentation
        "iicvat": trainer.IICVATTrainer,  # the basic iic with VAT as the basic data augmentation
        "iicgeovat": trainer.IICGeoVATTrainer,  # IIC with geo and vat as the data augmentation
        "iicgeovatmixup": trainer.IICGeoVATMixupTrainer,  # IIC with geo, vat and mixup as the data augmentation
        "imsat": trainer.IMSATAbstractTrainer,  # imsat without any regularization
        "imsatvat": trainer.IMSATVATTrainer,  # imsat with vat
        "imsatgeo": trainer.IMSATGeoTrainer,
        "imsatmixup": trainer.IMSATMixupTrainer,  # imsat with mixup
        "imsatvatmixup": trainer.IMSATVATMixupTrainer,  # imsat with vat + mixup
        "imsatvatgeo": trainer.IMSATVATGeoTrainer,  # imsat with geo+vat
        "imsatvatgeomixup": trainer.IMSATVATGeoMixupTrainer,  # imsat with geo vat and mixup
    }
    Trainer = trainer_mapping.get(config.get("Trainer").get("name").lower())
    assert Trainer, config.get("Trainer").get("name")
    return Trainer


if __name__ == '__main__':
    DEFAULT_CONFIG = "config/config_MNIST.yaml"
    merged_config = ConfigManger(
        DEFAULT_CONFIG_PATH=DEFAULT_CONFIG, verbose=True, integrality_check=True
    ).config

    # for reproducibility
    fix_all_seed(merged_config.get("Seed", 0))

    # get train loaders and validation loader
    train_loader_A, train_loader_B, val_loader = get_dataloader(merged_config)

    # create model:
    model = Model(
        arch_dict=merged_config["Arch"],
        optim_dict=merged_config["Optim"],
        scheduler_dict=merged_config["Scheduler"],
    )
    # if use automatic precision mixture training
    model = to_Apex(model, opt_level=None, verbosity=0)

    # get specific trainer
    Trainer = get_trainer(merged_config)

    clusteringTrainer = Trainer(
        model=model,
        train_loader_A=train_loader_A,
        train_loader_B=train_loader_B,
        val_loader=val_loader,
        config=merged_config,
        **merged_config["Trainer"]
    )
    clusteringTrainer.start_training()
    # clusteringTrainer.clean_up(wait_time=3)
