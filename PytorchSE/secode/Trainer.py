import torch.nn as nn
import torch
import pandas as pd
import os, sys
from tqdm import tqdm
import librosa, scipy
import pdb
import numpy as np
from scipy.io.wavfile import write as audiowrite
from util import get_filepaths, check_folder, make_spectrum, recons_spec_phase, cal_score

maxv = np.iinfo(np.int16).max

class Trainer:
    def __init__(self, model, epochs, epoch, best_loss, optimizer, 
                      criterion, device, loader,Test_path, writer, model_path, score_path, args):
#         self.step = 0
        self.epoch = epoch
        self.epochs = epochs
        self.best_loss = best_loss
        self.model = model.to(device)
        self.optimizer = optimizer


        self.device = device
        self.loader = loader
        self.criterion = criterion
        self.Test_path = Test_path

        self.train_loss = 0
        self.val_loss = 0
        self.writer = writer
        self.model_path = model_path
        self.score_path = score_path
        self.args = args

    def save_checkpoint(self,):
        state_dict = {
            'epoch': self.epoch,
            'model': self.model.state_dict(),
            'optimizer': self.optimizer.state_dict(),
            'best_loss': self.best_loss
            }
        check_folder(self.model_path)
        torch.save(state_dict, self.model_path)
    
    def slice_data(self,data,slice_size=64):
        # print("A",data,slice_size)
        # print("B",torch.split(data,slice_size,dim=1))
        # # print("C",torch.split(data,slice_size,dim=1)[:-1])
        #[Neil] Modify for CustomDataset
        data = torch.cat(torch.split(data,slice_size,dim=1),dim=0)
        # data = torch.cat(torch.split(data,slice_size,dim=1)[:-1],dim=0)
#         index = torch.randperm(data.shape[0])
#         return data[index]
        return data

    def _train_step(self, noisy, clean):
        device = self.device
        # print("noisy:",noisy)
        # print("clean:",clean)
        noisy, clean = noisy.to(device), clean.to(device)
        noisy, clean = self.slice_data(noisy), self.slice_data(clean)
#         pdb.set_trace()
        pred = self.model(noisy)
        loss = self.criterion(pred, clean)
        self.train_loss += loss.item()
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

#             if USE_GRAD_NORM:
#                 nn.utils.clip_grad_norm_(self.model['discriminator'].parameters(), DISCRIMINATOR_GRAD_NORM)
#             self.optimizer['discriminator'].step()


    def _train_epoch(self):
        self.train_loss = 0
        progress = tqdm(total=len(self.loader['train']), desc=f'Epoch {self.epoch} / Epoch {self.epochs} | train', unit='step')
        self.model.train()
        
#         for key in self.model.keys():
#             self.model[key].train()
#         noisy, clean = self.loader['train'].next()
#         while noisy is not None:
        #[Yo]
        print(next(iter(self.loader['train'])))
        exit()
        for (noisy, clean) in self.loader['train']:
            print('noisy',noisy)
            print('clean',clean)
#             self.step += 1

            self._train_step(noisy, clean)
            progress.update(1)
#             noisy, clean = self.loader['train'].next()
            
        progress.close()
        self.train_loss /= len(self.loader['train'])
        print(f'train_loss:{self.train_loss}')
        
    
#     @torch.no_grad()
    def _val_step(self, noisy, clean):
        device = self.device
        noisy, clean = noisy.to(device), clean.to(device)
        noisy, clean = self.slice_data(noisy), self.slice_data(clean)
        pred = self.model(noisy)
        loss = self.criterion(pred, clean)
        self.val_loss += loss.item()
        

    def _val_epoch(self):
        self.val_loss = 0
        progress = tqdm(total=len(self.loader['val']), desc=f'Epoch {self.epoch} / Epoch {self.epochs} | valid', unit='step')
        self.model.eval()
#         noisy, clean = self.loader['val'].next()
#         while noisy is not None:
        for noisy, clean in self.loader['val']:
            self._val_step(noisy, clean)
            progress.update(1)
#             noisy, clean = self.loader['val'].next()

            
        progress.close()

        self.val_loss /= len(self.loader['val'])
        print(f'val_loss:{self.val_loss}')
        
        if self.best_loss > self.val_loss:
            
            print(f"Save model to '{self.model_path}'")
            self.save_checkpoint()
            self.best_loss = self.val_loss
            
    def write_score(self,test_file,clean_path):
        
        self.model.eval()
        n_data,sr = librosa.load(test_file,sr=16000)
#         noisy = n_data
        c_data,sr = librosa.load(os.path.join(clean_path,'clean_'+'_'.join((test_file.split('/')[-1].split('_')[-2:])) ),sr=16000)
        n_data,n_phase,n_len = make_spectrum(y=n_data)
        n_data = torch.from_numpy(n_data.transpose()).to(self.device).unsqueeze(0)
        pred = self.model(n_data).cpu().detach().numpy()
        enhanced = recons_spec_phase(pred.squeeze().transpose(),n_phase,n_len)
        out_path = f"./Enhanced/{self.model.__class__.__name__}/{test_file.split('/')[-1]}"
        check_folder(out_path)
        audiowrite(out_path,16000,(enhanced* maxv).astype(np.int16))

#         s_pesq, s_stoi = cal_score(c_data,noisy)
        s_pesq, s_stoi = cal_score(c_data,enhanced)
        wave_name = test_file.split('/')[-1].split('.')[0]
        with open(self.score_path, 'a') as f:
            f.write(f'{wave_name},{s_pesq},{s_stoi}\n')

        

    def train(self):
       
        while self.epoch < self.epochs:
            self._train_epoch()
            self._val_epoch()
            self.writer.add_scalars(f'{self.args.task}/{self.model.__class__.__name__}_{self.args.optim}_{self.args.loss_fn}', {'train': self.train_loss},self.epoch)
            self.writer.add_scalars(f'{self.args.task}/{self.model.__class__.__name__}_{self.args.optim}_{self.args.loss_fn}', {'val': self.val_loss},self.epoch)
            self.epoch += 1
            
    
            
    def test(self):
        #[Yo] Modify Test_path
        # load model
        self.model.eval()
#         self.score_path = './Result/Test_Noisy.csv'
        checkpoint = torch.load(self.model_path)
        self.model.load_state_dict(checkpoint['model'])
        
        print(self.Test_path['noisy'])
        exit()
        test_folders = get_filepaths(self.Test_path['noisy'])
        clean_path = self.Test_path['clean']
        check_folder(self.score_path)
        if os.path.exists(self.score_path):
            os.remove(self.score_path)
        with open(self.score_path, 'a') as f:
            f.write('Filename,PESQ,STOI\n')
        for test_file in tqdm(test_folders):
            self.write_score(test_file,clean_path)
        
        data = pd.read_csv(self.score_path)
        pesq_mean = data['PESQ'].to_numpy().astype('float').mean()
        stoi_mean = data['STOI'].to_numpy().astype('float').mean()

        with open(self.score_path, 'a') as f:
            f.write(','.join(('Average',str(pesq_mean),str(stoi_mean)))+'\n')
#         with parallel_backend('multiprocessing', n_jobs=20):
#             val_pesq = Parallel()(delayed(write_score)
#                                              (16000,val_list[k][0], val_list[k][1], 'wb')
#                                               for k in range(len(val_list)))
        
        
class data_prefetcher():
    def __init__(self, loader):
        self.loader = iter(loader)
        self.stream = torch.cuda.Stream()
        self.len = len(loader)
        self.preload()

    def preload(self):
        try:
            self.next_noisy, self.next_clean = next(self.loader)
        except StopIteration:
            self.next_noisy = None
            self.next_clean = None
            return
        with torch.cuda.stream(self.stream):
            self.next_noisy = self.next_noisy.cuda(non_blocking=True)
            self.next_clean = self.next_clean.cuda(non_blocking=True)
            
    def next(self):
        torch.cuda.current_stream().wait_stream(self.stream)
        noisy = self.next_noisy
        clean = self.next_clean
        self.preload()
        return noisy,clean
    
    def length(self):
        return self.len
    
    