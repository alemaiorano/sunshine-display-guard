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
