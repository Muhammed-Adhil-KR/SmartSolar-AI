from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from .forms import LocationSearchForm, SolarSystemForm, BatteryForm, GridConfigurationForm
from .services import search_locations, reverse_geocode, sync_system_dependencies
from .decorators import next_setup_step


def build_step_context(system, current_key):
    """
    Builds the list of steps for the setup-flow step indicator, adapting
    to whichever steps are actually relevant once system_type is known.
    """
    steps = [('system', 'System')]
    steps.append(('location', 'Location'))
    if system:
        if system.needs_battery:
            steps.append(('battery', 'Battery'))
        if system.needs_grid_config:
            steps.append(('grid', 'Grid'))

    keys = [key for key, _ in steps]
    current_index = keys.index(current_key) if current_key in keys else 0

    step_list = []
    for i, (key, label) in enumerate(steps):
        if i < current_index:
            status = 'done'
        elif i == current_index:
            status = 'active'
        else:
            status = 'pending'
        step_list.append({'label': label, 'status': status})
    return step_list


@login_required
def setup_system(request):
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

    steps = build_step_context(instance, 'system')
    return render(request, 'solar/setup_system.html', {'form': form, 'steps': steps})


@login_required
def setup_location(request):
    system = getattr(request.user, 'solarsystem', None)
    if not system:
        return redirect('solar:setup_system')

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

    steps = build_step_context(system, 'location')
    return render(request, 'solar/setup_location.html', {'form': form, 'results': results, 'steps': steps})


@login_required
def confirm_location(request):
    if request.method != 'POST':
        return redirect('solar:setup_location')

    system = getattr(request.user, 'solarsystem', None)
    if not system:
        return redirect('solar:setup_system')

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

    system.latitude = latitude
    system.longitude = longitude
    system.location_name = location_name
    system.save()

    messages.success(request, f"Location set to {location_name}.")
    return redirect(next_setup_step(request.user) or 'dashboard:home')


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

    steps = build_step_context(system, 'battery')
    return render(request, 'solar/setup_battery.html', {'form': form, 'steps': steps})


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

    steps = build_step_context(system, 'grid')
    return render(request, 'solar/setup_grid.html', {'form': form, 'steps': steps})




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

from django.shortcuts import get_object_or_404
from .models import Appliance
from .forms import ApplianceForm


@login_required
def appliance_list(request):
    appliances = Appliance.objects.filter(user=request.user)
    return render(request, 'solar/appliance_list.html', {'appliances': appliances})


@login_required
def appliance_add(request):
    if request.method == 'POST':
        form = ApplianceForm(request.POST)
        if form.is_valid():
            appliance = form.save(commit=False)
            appliance.user = request.user
            appliance.save()
            messages.success(request, f"'{appliance.name}' added successfully.")
            return redirect('solar:appliance_list')
    else:
        form = ApplianceForm()
    return render(request, 'solar/appliance_form.html', {'form': form, 'mode': 'add'})


@login_required
def appliance_edit(request, pk):
    # get_object_or_404 with user=request.user means another user's appliance
    # ID simply doesn't match a query result — genuine 404, not a leak.
    appliance = get_object_or_404(Appliance, pk=pk, user=request.user)
    if request.method == 'POST':
        form = ApplianceForm(request.POST, instance=appliance)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{appliance.name}' updated.")
            return redirect('solar:appliance_list')
    else:
        form = ApplianceForm(instance=appliance)
    return render(request, 'solar/appliance_form.html', {'form': form, 'mode': 'edit', 'appliance': appliance})


@login_required
def appliance_toggle_active(request, pk):
    appliance = get_object_or_404(Appliance, pk=pk, user=request.user)
    appliance.is_active = not appliance.is_active
    appliance.save()
    status = "reactivated" if appliance.is_active else "deactivated"
    messages.success(request, f"'{appliance.name}' {status}.")
    return redirect('solar:appliance_list')


@login_required
def appliance_delete(request, pk):
    appliance = get_object_or_404(Appliance, pk=pk, user=request.user)
    if request.method == 'POST':
        name = appliance.name
        appliance.delete()
        messages.success(request, f"'{name}' permanently deleted.")
        return redirect('solar:appliance_list')
    return render(request, 'solar/appliance_confirm_delete.html', {'appliance': appliance})