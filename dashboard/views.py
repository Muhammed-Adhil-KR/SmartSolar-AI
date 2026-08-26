from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from solar.decorators import setup_required


@login_required
@setup_required
def home(request):
    return render(request, 'dashboard/home.html')