import micropython
import array

aux = array.array('h', [-1] * 2)

@micropython.viper

def prova_aritmetica(vet: ptr16):

    sample = int(vet[0])

    print("dentro viper: ", sample)

    # ESTENSIONE DEL SEGNO
    sample = (sample << 16) >> 16

    print("ora con il segno giusto vale", sample)

    vet[1] = sample


prova_aritmetica(aux)

print("val:", aux[0], "viper ha capito: ", aux[1])