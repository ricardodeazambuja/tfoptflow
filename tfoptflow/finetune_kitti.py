"""
PWC-Net model training.
Written by Phil Ferriere
Licensed under the MIT License (see LICENSE for details)
Tensorboard:
    tensorboard --logdir=<checkpoint_directory>
"""
import tensorflow as tf
from dataset_mixer import MixedDataset
from dataset_kitti import KITTIDataset
from model_pwcnet import ModelPWCNet

# arguments for paths
ckpt_path = '/home/azambuja/scratch/pretrained/pwcnet.ckpt-595000'
save_path = '/home/azambuja/scratch/kitti_flow_ckpt_training/'
data_path = '/home/azambuja/scratch/'
kitti15 = 'kitti_flow15/'
kitti12 = 'kitti_flow12/'

# Main Function
def _main():

    # Set controller device and devices
    # A one-gpu setup would be something like controller='/device:GPU:0' and gpu_devices=['/device:GPU:0']
    gpu_devices = ['/device:GPU:0', '/device:GPU:1', '/device:GPU:2', '/device:GPU:3']
    controller = '/device:CPU:0'

    # Useful settings
    batch_size = 8
    img_size = (256, 448)

    # Dataset options
    ds_opts = {
        'batch_size': batch_size,
        'verbose': False,
        'in_memory': False,  # True loads all samples upfront, False loads them on-demand
        'crop_preproc': img_size,  # None or (h, w), use (384, 768) for FlyingThings3D
        'scale_preproc': None,  # None or (h, w),
        'type': 'noc', # ['clean' | 'final'] for MPISintel, ['noc' | 'occ'] for KITTI, 'into_future' for FlyingThings3D
        'tb_test_imgs': False,  # If True, make test images available to model in training mode
        # Sampling and split options
        'random_seed': 1337,  # random seed used for sampling
        'val_split': 0.04,  # portion of data reserved for the validation split
        # Augmentation options
        'aug_type': 'heavy',  # in [None, 'basic', 'heavy'] to add augmented data to training set
        'aug_labels': True,  # If True, augment both images and labels; otherwise, only augment images
        'fliplr': 0.5,  # Horizontally flip 50% of images
        'flipud': 0.1,  # Vertically flip 50% of images
        'translate': (0.5, 0.05), # Translate 50% of images by a value between -5 and +5 percent of original size on x- and y-axis independently
        'scale': (0.5, 0.05),  # Scale 50% of images by a factor between 95 and 105 percent of original size
    }

    # Load train dataset
    ds_1 = KITTIDataset(mode='train_with_val', ds_root=data_path + kitti12, options=ds_opts)
    ds_2 = KITTIDataset(mode='train_with_val', ds_root=data_path + kitti15, options=ds_opts)
    ds = MixedDataset(mode='train_with_val', datasets=[ds_1, ds_2], options=ds_opts)

    # Display dataset configuration
    ds.print_config()

    # Training options
    nn_opts = {
        'verbose': False,
        'ckpt_path': ckpt_path,  # original checkpoint to finetune
        'ckpt_dir': save_path,  # where finetuning checkpoints are stored
        'max_to_keep': 10,
        'x_dtype': tf.float32,  # image pairs input type
        'x_shape': [2, img_size[0], img_size[1], 3],  # image pairs input shape [2, H, W, 3]
        'y_dtype': tf.float32,  # u,v flows output type
        'y_shape': [img_size[0], img_size[1], 2],  # u,v flows output shape [H, W, 2]
        'train_mode': 'fine-tune',  # in ['train', 'fine-tune']
        'adapt_info': None,  # if predicted flows are padded by the model, crop them back by to this size
        'sparse_gt_flow': True,  # if gt flows are sparse (KITTI), only compute average EPE where gt flows aren't (0., 0.)
        # Logging/Snapshot params
        'display_step': 100,  # show progress every 100 training batches
        'snapshot_step': 1000,  # save trained model every 1000 training batches
        'val_step': 1000,  # Test trained model on validation split every 1000 training batches
        'val_batch_size': -1,  # Use -1 to use entire validation split, or set number of val samples (0 disables it)
        'tb_val_imgs': 'top_flow',  # None, 'top_flow', or 'pyramid'; runs model on batch_size val images, log results
        'tb_test_imgs': None,  # None, 'top_flow', or 'pyramid'; runs trained model on batch_size test images, log results
        # Multi-GPU config
        # list devices on which to run the model's train ops (can be more than one GPU)
        'gpu_devices': gpu_devices,
        # controller device to put the model's variables on (usually, /cpu:0 or /gpu:0 -> try both!)
        'controller': controller,
        # Training config and hyper-params
        'use_tf_data': True,  # Set to True to get data from tf.data.Dataset; otherwise, use feed_dict with numpy
        'use_mixed_precision': False,  # Set to True to use mixed precision training (fp16 inputs)
        'loss_scaler': 128.,  # Loss scaler (only used in mixed precision training)
        'batch_size': batch_size,
        'lr_policy': 'multisteps',  # choose between None, 'multisteps', and 'cyclic'; adjust the max_steps below too
        # Multistep lr schedule
        'init_lr': 1e-05,  # initial learning rate
        'max_steps': 200000 * 8 / ds_opts['batch_size'],  # max number of training iterations (i.e., batches to run)
        'lr_boundaries': [80000, 120000, 160000, 200000],  # step schedule boundaries
        'lr_values': [1e-05, 5e-06, 2.5e-06, 1.25e-06, 6.25e-07],  # step schedule values
        # Cyclic lr schedule
        'cyclic_lr_max': 2e-05,  # maximum bound
        'cyclic_lr_base': 1e-06,  # min bound
        'cyclic_lr_stepsize': 20000 * 8 / ds_opts['batch_size'],  # step schedule values
        # 'max_steps': 200000, # max number of training iterations
        # Loss functions hyper-params
        'loss_fn': 'loss_multiscale',  # 'loss_robust' doesn't really work; the loss goes down but the EPE doesn't
        'alphas': [0.32, 0.08, 0.02, 0.01, 0.005],  # See 'Implementation details" on page 5 of ref PDF
        'gamma': 0.0004,  # See 'Implementation details" on page 5 of ref PDF
        'q': 0.1,  # See 'Implementation details" on page 5 of ref PDF
        'epsilon': 0.,  # See 'Implementation details" on page 5 of ref PDF
        # Model hyper-params
        'pyr_lvls': 6,  # number of feature levels in the flow pyramid
        'flow_pred_lvl': 2,  # which level to upsample to generate the final optical flow prediction
        'search_range': 4,  # cost volume search range
        # if True, use model with dense connections (4705064 params w/o, 9374274 params with (no residual conn.))
        'use_dense_cx': True,
        # if True, use model with residual connections (4705064 params w/o, 6774064 params with (+2069000) (no dense conn.))
        'use_res_cx': True,
    }

    # Instantiate the model and display the model configuration
    nn = ModelPWCNet(mode='train_with_val', options=nn_opts, dataset=ds)
    nn.print_config()

    # Train the model
    nn.train()


if __name__ == "__main__":
    _main()