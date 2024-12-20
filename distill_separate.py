import utils
import torch
import numpy as np
import dataloader
import time
from parse import parse_args
import multiprocessing
import os
from os.path import join
from model import LightGCN, PureMF, UltraGCN, SGCN
from trainers import GraphRecTrainer
from utils import EarlyStopping
import glob

# Function to dynamically pick the correct tar file
def get_tar_file(directory, prefix):
    """
    Find the tar file in the directory that matches the given prefix.
    """
    search_pattern = os.path.join(directory, f"{prefix}*.pth.tar")
    matching_files = glob.glob(search_pattern)
    if not matching_files:
        print(f"No tar file found with prefix: {prefix}")
        return None
    # If multiple matches are found, pick the first (or handle as needed)
    return matching_files[0]


def cprint(words : str):
    print(f"\033[0;30;43m{words}\033[0m")


os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
args = parse_args()

ROOT_PATH = "./"
CODE_PATH = join(ROOT_PATH, 'code')
DATA_PATH = join(ROOT_PATH, 'data')
BOARD_PATH = join(CODE_PATH, 'runs')
FILE_PATH = join(CODE_PATH, 'checkpoints')
import sys
sys.path.append(join(CODE_PATH, 'sources'))


if not os.path.exists(FILE_PATH):
    os.makedirs(FILE_PATH, exist_ok=True)

args.device = torch.device('cuda' if torch.cuda.is_available() else "cpu")
args.cores = multiprocessing.cpu_count() // 2

utils.set_seed(args.seed)

# let pandas shut up
from warnings import simplefilter
simplefilter(action="ignore", category=FutureWarning)

#Recmodel = register.MODELS[world.model_name](world.config, dataset)
dataset = dataloader.Loader(args)
if args.model_name == 'LightGCN':
    model = LightGCN(args, dataset)
elif args.model_name == 'UltraGCN':
    constraint_mat = dataset.getConstraintMat()
    ii_neighbor_mat, ii_constraint_mat = dataset.get_ii_constraint_mat()
    model = UltraGCN(args, dataset, constraint_mat, ii_constraint_mat, ii_neighbor_mat)
elif args.model_name == 'SGCN':
    model = SGCN(args, dataset)
else:
    model = PureMF(args, dataset)
model = model.to(args.device)
trainer = GraphRecTrainer(model, dataset, args)

checkpoint_path = utils.getFileName("./checkpoints/", args)
print(f"load and save to {checkpoint_path}")

if args.do_eval:
    if args.data_name == 'movie_lenz_rating_1':
        prefix = f"movie_lenz_rating_1-LightGCN"
        checkpoint_path = get_tar_file("./checkpoints", prefix)
        # checkpoint_path = './checkpoints/movie_lenz_rating_1-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar' 
    print(f'Load model from {checkpoint_path} for test!')
    trainer.load(checkpoint_path)

    [distill_row, distill_col, distill_val] = trainer.generateKorderGraph(userK=args.distill_userK, itemK=args.distill_itemK, threshold=args.distill_thres)
    dataset.reset_graph([distill_row, distill_col, distill_val])
    model.dataset = dataset
    trainer.dataset = dataset
    checkpoint_path = utils.getDistillFileName("./checkpoints_distill/", args)
    trainer.model.load_state_dict(torch.load(checkpoint_path))
    model.n_layers = args.distill_layers
    model.dataset = dataset
    model.reset_graph()
    print(f'Load model from {checkpoint_path} for test!')
    #scores, result_info, _ = trainer.test(0, full_sort=True)
    scores, result_info, _ = trainer.complicated_eval()

else:
    prefix = f"movie_lenz_rating_{args.data_name.split('_')[-1]}-LightGCN"
    checkpoint_path = get_tar_file("./checkpoints", prefix)
    # if args.data_name == 'movie_lenz_rating_1':
    #     checkpoint_path = './checkpoints/movie_lenz_rating_1-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar'
    # elif args.data_name == 'movie_lenz_rating_2':
    #     checkpoint_path = './checkpoints/movie_lenz_rating_2-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar'    
    # elif args.data_name == 'movie_lenz_rating_3':
    #     checkpoint_path = './checkpoints/movie_lenz_rating_3-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar'    
    # elif args.data_name == 'movie_lenz_rating_4':
    #     checkpoint_path = './checkpoints/movie_lenz_rating_4-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar'    
    # elif args.data_name == 'movie_lenz_rating_5':
    #     checkpoint_path = './checkpoints/movie_lenz_rating_5-LightGCN-movie_lenz_rating_1-3-0.001-0.001-1000-1-0.3.pth.tar'  

    print(f'Load model from {checkpoint_path} for test!')
    trainer.load(checkpoint_path)

    [distill_row, distill_col, distill_val] = trainer.generateKorderGraph(userK=args.distill_userK, itemK=args.distill_itemK, threshold=args.distill_thres)
    dataset.reset_graph([distill_row, distill_col, distill_val])
    model.dataset = dataset
    model.reset_all()
    model.n_layers = args.distill_layers
    trainer.optim = torch.optim.Adam(model.parameters(), lr=0.001)
    trainer.dataset = dataset
    checkpoint_path = utils.getDistillFileName("./checkpoints_distill/", args)
    early_stopping = EarlyStopping(checkpoint_path, patience=50, verbose=True)
    for epoch in range(args.epochs):
        trainer.train(epoch)
        if (epoch+1) %10==0:
            scores, _, _ = trainer.valid(epoch, full_sort=True)
            early_stopping(np.array(scores[-1:]), trainer.model)
            if early_stopping.early_stop:
                print("Early stopping")
                break
    print('---------------Change to Final testing!-------------------')
    # load the best model
    trainer.model.load_state_dict(torch.load(checkpoint_path))
    valid_scores, _, _ = trainer.valid('best', full_sort=True)
    #trainer.args.train_matrix = test_rating_matrix
    scores, result_info, _ = trainer.complicated_eval()
