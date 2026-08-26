from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .forms import LocationSearchForm, SolarSystemForm, BatteryForm, GridConfigurationForm
from .services import search_locations, reverse_geocode, sync_system_dependencies
from .decorators import next_setup_step


@login_required
def setup_location(request):
    results = []
    if request.method == 'POST':
        form = LocationSearchForm(request.POST)
        if form.is_valid():
            query = form.cleaned_data['query']
            results = search_locations(query)
            if not results:
                messages.warning(request, "No locations found. Try a different spelling or a nearby larger town.")
    else:
        form = LocationSearchForm()

    return render(request, 'solar/setup_location.html', {'form': form, 'results': results})


@login_required
def confirm_location(request):
    if request.method != 'POST':
        return redirect('solar:setup_location')

    try:
        latitude = float(request.POST.get('latitude'))
        longitude = float(request.POST.get('longitude'))
    except (TypeError, ValueError):
        messages.error(request, "Invalid location selected. Please try again.")
        return redirect('solar:setup_location')

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        messages.error(request, "Invalid coordinates received. Please try again.")
        return redirect('solar:setup_location')

    location_name = reverse_geocode(latitude, longitude)
    if not location_name:
        location_name = f"Lat {latitude:.4f}, Lon {longitude:.4f}"

    profile = request.user.profile
    profile.latitude = latitude
    profile.longitude = longitude
    profile.location_name = location_name
    profile.save()

    messages.success(request, f"Location set to {location_name}.")
    return redirect('solar:setup_system')


@login_required
def setup_system(request):
    if not request.user.profile.has_location:
        return redirect('solar:setup_location')

    instance = getattr(request.user, 'solarsystem', None)
    if request.method == 'POST':
        form = SolarSystemForm(request.POST, instance=instance)
        if form.is_valid():
            system = form.save(commit=False)
            system.user = request.user
            system.save()
            if system.capacity_kw > 50:
                messages.warning(request, "That's a large capacity for a household system — double-check the value.")
            return redirect(next_setup_step(request.user) or 'dashboard:home')
    else:
        form = SolarSystemForm(instance=instance)

    return render(request, 'solar/setup_system.html', {'form': form})


@login_required
def setup_battery(request):
    system = getattr(request.user, 'solarsystem', None)
    if not system or not system.needs_battery:
        return redirect(next_setup_step(request.user) or 'dashboard:home')

    instance = getattr(request.user, 'battery', None)
    if request.method == 'POST':
        form = BatteryForm(request.POST, instance=instance)
        if form.is_valid():
            battery = form.save(commit=False)
            battery.user = request.user
            battery.save()
            return redirect(next_setup_step(request.user) or 'dashboard:home')
    else:
        form = BatteryForm(instance=instance)

    return render(request, 'solar/setup_battery.html', {'form': form})


@login_required
def setup_grid(request):
    system = getattr(request.user, 'solarsystem', None)
    if not system or not system.needs_grid_config:
        return redirect(next_setup_step(request.user) or 'dashboard:home')

    instance = getattr(request.user, 'gridconfiguration', None)
    if request.method == 'POST':
        form = GridConfigurationForm(request.POST, instance=instance)
        if form.is_valid():
            grid = form.save(commit=False)
            grid.user = request.user
            grid.save()
            return redirect(next_setup_step(request.user) or 'dashboard:home')
    else:
        form = GridConfigurationForm(instance=instance)

    return render(request, 'solar/setup_grid.html', {'form': form})


@login_required
def edit_system(request):
    instance = getattr(request.user, 'solarsystem', None)
    if not instance:
        return redirect('solar:setup_system')

    if request.method == 'POST':
        form = SolarSystemForm(request.POST, instance=instance)
        if form.is_valid():
            system = form.save()
            if system.capacity_kw > 50:
                messages.warning(request, "That's a large capacity for a household system — double-check the value.")

            removed = sync_system_dependencies(request.user, system)
            if removed:
                messages.info(request, f"Removed no-longer-applicable settings: {', '.join(removed)}.")

            next_step = next_setup_step(request.user)
            if next_step:
                messages.info(request, "Your new system type needs a bit more information.")
                return redirect(next_step)

            messages.success(request, "Solar system details updated.")
            return redirect('dashboard:home')
    else:
        form = SolarSystemForm(instance=instance)

    return render(request, 'solar/edit_system.html', {'form': form})

@login_required
def edit_battery(request):
    instance = getattr(request.user, 'battery', None)
    if request.method == 'POST':
        form = BatteryForm(request.POST, instance=instance)
        if form.is_valid():
            battery = form.save(commit=False)
            battery.user = request.user
            battery.save()
            messages.success(request, "Battery details updated.")
            return redirect('dashboard:home')
    else:
        form = BatteryForm(instance=instance)
    return render(request, 'solar/edit_battery.html', {'form': form})


@login_required
def edit_grid(request):
    instance = getattr(request.user, 'gridconfiguration', None)
    if request.method == 'POST':
        form = GridConfigurationForm(request.POST, instance=instance)
        if form.is_valid():
            grid = form.save(commit=False)
            grid.user = request.user
            grid.save()
            messages.success(request, "Grid configuration updated.")
            return redirect('dashboard:home')
    else:
        form = GridConfigurationForm(instance=instance)
    return render(request, 'solar/edit_grid.html', {'form': form})