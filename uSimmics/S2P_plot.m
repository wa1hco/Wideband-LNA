clear all
fid = fopen('/home/jeff/qucs/Wideband_LNA/TQP3M9036-s-parameters/TQP3M9036_LNA_MODE_S-PARS.S2P', 'r');
fskipl(fid, 13);

row = 1;

while (true)
  line = fgets(fid);
  if (line == -1)
    break;
  endif

  data = sscanf(line, '%f %f %f %f %f %f %f %f %f');
  if (length(data) != 9)
    disp("end of data");
    break;
  endif

  freq(row) = data(1);
  freqMHz = freq/1e6;
  s11(row) = complex(data(2), data(3));
  s12(row) = complex(data(4), data(5));
  s21(row) = complex(data(5), data(7));
  s22(row) = complex(data(8), data(9));
  row = row + 1;
endwhile
disp("s2p data read complete");
figure(1); clf; grid on; hold on;
plot(freqMHz, real(s11));
plot(freqMHz, real(s12));
plot(freqMHz, real(s21));
plot(freqMHz, real(s22));


