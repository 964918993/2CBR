# Cross-class Bias Rectification for Point Cloud Few-shot Segmentation

## Installation
- Install `python` --This repo is tested with `python 3.6.8`.
- Install `pytorch` with CUDA -- This repo is tested with `torch 1.4.0`, `CUDA 10.1`. 
It may work with newer versions, but that is not gauranteed.
- Install `faiss` with cpu version
   ```
   conda install faiss-cpu -c pytorch
   ```

- Install 'torch-cluster' with the corrreponding torch and cuda version
	```
	pip install torch-cluster==latest+cu101 -f https://pytorch-geometric.com/whl/torch-1.4.0.html
	```
- Install dependencies
    ```
    pip install tensorboard h5py transforms3d
    ```

## Usage
### Data preparation
#### S3DIS
1. Download [S3DIS Dataset Version 1.2](http://buildingparser.stanford.edu/dataset.html).
2. Re-organize raw data into `npy` files by running
   ```
   cd ./preprocess
   python collect_s3dis_data.py --data_path $path_to_S3DIS_raw_data
   ```
   The generated numpy files are stored in `./datasets/S3DIS/scenes/` by default.
3. To split rooms into blocks, run 

    ```python ./preprocess/room2blocks.py --data_path ./datasets/S3DIS/scenes/```
    
    One folder named `blocks_bs1_s1` will be generated under `./datasets/S3DIS/` by default. 
   
#### ScanNet
1. Download [ScanNet V2](http://www.scan-net.org/).
2. Re-organize raw data into `npy` files by running
	```
	cd ./preprocess
	python collect_scannet_data.py --data_path $path_to_ScanNet_raw_data
	```
   The generated numpy files are stored in `./datasets/ScanNet/scenes/` by default.
3. To split rooms into blocks, run 

    ```python ./preprocess/room2blocks.py --data_path ./datasets/ScanNet/scenes/ --dataset scannet```
    
    One folder named `blocks_bs1_s1` will be generated under `./datasets/ScanNet/` by default. 

### Running 
#### Training
First, pretrain the segmentor which includes feature extractor module on the available training set (We provide our own pre-training model under 'log_s3dis_pretrain'.):
    
    cd scripts
    bash pretrain_segmentor.sh

Second, train our method:
	
	bash scripts/train_attMPTI.sh


#### Evaluation
    
    bash scripts/eval_attMPTI.sh

#### Note
1. The above scripts are used for 2-way 1-shot task on S3DIS (S1). You can modify the corresponding hyperparameters (SPLIT, dataset and model_checkpoint_path if you run evaluation script) to conduct experiments on other settings. 
2. We provide pre-training models and related models in the paper, but the sampling process of the test set is random, so there will be some errors in the results when testing.

## Acknowledgement
We thank [AttMPTI (pytorch)](https://github.com/Na-Z/attMPTI) for sharing their source code.
