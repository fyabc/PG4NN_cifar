@rem The original valid_freq is 2500 (2500 * 20 = 50000 data, one valid point per epoch)
python train.py G.dataset=mnist G.train_type=@raw@ valid_freq=250
