# Sunshine Display Guard

Automação experimental de telas para Linux com GNOME/Mutter, usando Sunshine
no host e Moonlight no cliente. Preserva layouts físicos, usa uma saída virtual
já preparada e acompanha resolução/orientação da tela escolhida no cliente.

Leia o [guia de instalação](SETUP.md), os [limites](COMPATIBILITY.md) e a
[recuperação](RECOVERY.md) antes de ativar. Os nomes de conectores, serviços,
portas, destinos e caminhos vêm da configuração local; nenhum perfil de máquina
é distribuído. Não é um driver de monitor virtual e não instala firmware,
pareamentos nem credenciais.

O exemplo começa sem monitor de reserva escolhido e sem sincronização de captura.
O instalador mostra um plano por padrão. A instalação inicia somente o observador
passivo; ativar a política de telas é uma etapa explícita do usuário.

Monitor conectado ou DPMS ligado não comprova que o painel está ligado no botão.
Sem monitor físico, é necessária uma reserva utilizável. Sem qualquer saída,
não há framebuffer capturável. Boot/login presencial, suspensão e todas as
combinações de hardware não foram certificados.

Licença MIT. O projeto é independente do Sunshine e do Moonlight.


As [correções incluídas](CORRECTIONS.md) e a [validação](VALIDATION.md#real-session-follow-up)
estão documentadas separadamente. O núcleo recebeu validação em quatro sessões
reais, com retrato, horizontal, reconexão e journal filho encerrado. A restauração
foi automática; houve jitter/perda de quadros medidos. Isso não certifica o
controlador genérico inteiro nem todos os hardwares. Logs brutos e dados dos
ambientes usados na validação não são publicados.

## Tela virtual mesmo com dois monitores físicos

Há um perfil opcional `--exclusive-reserve`: ele usa apenas a reserva configurada
para a sessão remota, mesmo com monitores físicos estendidos ou espelhados, e
restaura o layout anterior ao sair. Durante esse modo, as telas físicas deixam
de compor o desktop; não é uso local/remoto independente simultâneo. O padrão
continua preservando o layout físico.

```sh
/usr/bin/python3 scripts/app_hooks.py --name 'Remote Desktop (Virtual)' --exclusive-reserve
/usr/bin/python3 scripts/app_hooks.py --name 'Remote Desktop (Virtual)' --exclusive-reserve --apply
```

O primeiro comando é preview. Escolha o novo aplicativo no Moonlight após atualizar
a instalação/lista de apps com streams fechados. A reserva DRM precisa estar
preparada e configurada; o utilitário não instala um driver virtual.
[Requisitos, restauração e limites de captura](EXCLUSIVE-RESERVE.md).
